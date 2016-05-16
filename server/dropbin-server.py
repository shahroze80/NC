import sys
import argparse
import socket
import os
import threading
import base64
import json
import datetime
import shutil
import queue

sharefile_changes_queue=queue.Queue()

last_sync={}
sharefiles={}
selectfiles={}
Active=True
# last_sync_lock=threading.Lock()
# sharefiles_lock()=threading.Lock()
# selectfiles_lock=threading.Lock()

def get_last_sync(username):
    return last_sync[username]

def set_last_sync(username,last_sync_date):
    global last_sync
    last_sync[username]=last_sync_date

def check_membership_last_sync(username):
    return username in last_sync

def get_sharefiles(username=None):
    if username:
        return sharefiles[username]
    return  sharefiles

def set_sharefiles(username,sharefile):
    global sharefiles
    sharefiles[username]=sharefile

def check_membership_sharefiles(username):
    return username in sharefiles

def get_selectfiles(username=None):
    if username:
        return selectfiles[username]
    return selectfiles

def set_selectfiles(username,selectfile):
    global selectfiles
    selectfiles[username]=selectfile

def check_membership_selectfiles(username):
    return username in selectfiles


def get_user_dir(username):
    path = os.path.join(os.getcwd(), username)
    os.makedirs(path, exist_ok=True)
    return path

def handle_shared_clients(username,filename,last_sync):
    print ("handle_sharefile_changes",username,filename)
    changes={}
    if check_membership_sharefiles(username):
        sharefile=get_sharefiles(username)
        print ("sharefile",sharefile)
        if filename in sharefile:
            clients_to_add_file=sharefile[filename]
            changes[filename]=clients_to_add_file
    else:
        for client,shared_files in sharefiles.items():
            
            print ("for loop of handle clients",client,sharefiles)
            # print ('sharefiles',sharefiles)
            if filename in shared_files:
                print ('filename in sharedfiles')
                clients_to_add_file= shared_files[filename]
                clients_to_add_file.append(client)
                clients_to_add_file.remove(username)
                changes[filename]=clients_to_add_file
    print ("changes in shared files due to modificiation in sharedfiles",changes)
    shared_file_add(changes,username,last_sync) 

def add_file(client_dir, filename, data,modified_date=None):
    path = os.path.join(client_dir, filename)
    with open(path, 'wb') as file:
        file.write(base64.b64decode(data.encode('utf-8')))
    if modified_date:
        os.utime(path,(0,modified_date))

def delete_file(client_dir, filename):
    path = os.path.join(client_dir, filename)
    if os.path.exists(path):
        os.remove(path)

# copied from client
def send_msg(conn, msg):
    serialized = json.dumps(msg).encode('utf-8')
    conn.send(b'%d\n' % len(serialized))
    conn.sendall(serialized)

def get_message(conn):
    length_str = b''
    char = conn.recv(1)
    while char != b'\n':
        length_str += char
        char = conn.recv(1)
    total = int(length_str)
    off = 0
    msg = b''
    while off < total:
        temp = conn.recv(total - off)
        off = off + len(temp)
        msg = msg + temp
    return json.loads(msg.decode('utf-8'))

def send_file_list(conn,client_dir):
    files = os.listdir(client_dir)
    files = [file for file in files if os.path.isfile(os.path.join(client_dir, file))]
    file_list = {}
    for file in files:
        path = os.path.join(client_dir, file)
        mtime = os.path.getmtime(path)
        # ctime = os.path.getctime(path)
        file_list[file] = mtime
    # print ('file_list: ',file_list)
    send_msg(conn,file_list)

def send_file(conn,filename):
    with open(filename, "rb") as file:
        data = base64.b64encode(file.read()).decode('utf-8')
        msg = {
            'type': 'file_add',
            'filename': filename,
            'data': data,
            'modified_date' : os.path.getmtime(filename)
        }
        send_msg(conn, msg)

def send_last_sync(conn,username):
    if check_membership_last_sync(username):
        msg={
            'last_sync':str(get_last_sync(username))
        }
        send_msg(conn,msg)
    else:
        msg={
            'last_sync' : 'min'
        }
        send_msg(conn,msg)

def store_last_sync(username,str_date):
    date=datetime.datetime.strptime(str_date, "%Y-%m-%d %H:%M:%S.%f")
    # last_sync[username]=date
    set_last_sync(username,date)

def parse_sharefile(raw_data):
    sharefile={}
    data=raw_data.split('\n')
    for line in data:
        words=line.rstrip('\n').split(' ')
        filename=words.pop(0)
        sharefile[filename]=words
    return sharefile

def get_user_changes(sharefile_a,sharefile_b,selectfile):
    file_user={}
    for filename,users_new in sharefile_a.items():
        if (selectfile and filename in sharefile_b and filename in selectfile) or (selectfile==None and filename in sharefile_b):
            users_old=sharefile_b[filename]
            users_added=list(set(users_new)-set(users_old))
            if users_added:
                file_user[filename]=users_added
    return file_user

def get_changes_sharefile(sharefile_new,sharefile_old,selectfile=None):
    changes={}
    print('sharefile_new',sharefile_new)
    print('sharefile_old',sharefile_old)
    print('selectfile',selectfile)

    if selectfile:
        old_minus_new={k:v for k,v in sharefile_old.items() if k not in sharefile_new and k in selectfile}
    else:
        old_minus_new={k:v for k,v in sharefile_old.items() if k not in sharefile_new}
    if old_minus_new:
        changes['file_delete']=old_minus_new

    if selectfile:
        new_minus_old={k:v for k,v in sharefile_new.items() if k not in sharefile_old and k in selectfile}
    else:
        new_minus_old={k:v for k,v in sharefile_new.items() if k not in sharefile_old}
    if new_minus_old:
        changes['file_add']=new_minus_old

    user_added=get_user_changes(sharefile_new,sharefile_old,selectfile)
    if user_added:
        changes['user_add']=user_added

    user_removed=get_user_changes(sharefile_old,sharefile_new,selectfile)
    if user_removed:
        changes['user_removed']=user_removed

    print ('changes in sharefile ',changes)
    return changes

def shared_file_add(changes,username,last_sync_str):
    print('changes in shared_file_add',changes)
    for filename,users in changes.items():
        src=os.path.join(os.getcwd(),username,filename)
        for user in users:
            if os.path.isdir(os.path.join(os.getcwd(),user)):
                store_last_sync(user,last_sync_str)
                dst=os.path.join(os.getcwd(),user,filename)
                print ('there so far')
                print ('src',src,'dest',dst)
                if os.path.exists(src):
                    # print ("inside it")
                    shutil.copy2(src,dst)
                    print('copied %s to %s' %(src,dst))
                else:
                    print('files not yet on server')
                    sharefile_changes_queue.put(changes)

def shared_file_delete(changes,last_sync_str):
    for filename,users in changes.items():
        for user in users:
            if os.path.isdir(os.path.join(os.getcwd(),user)):   
                store_last_sync(user,last_sync_str)
                path=os.path.join(os.getcwd(),user,filename)
                if os.path.exists(path):
                    print('deleted %s' % path)
                    os.remove(path)


def handle_sharefile_changes(changes,username,last_sync_str):
    if 'file_add' in changes:
        shared_file_add(changes['file_add'],username,last_sync_str)
    if 'user_add' in changes:
        shared_file_add(changes['user_add'],username,last_sync_str)
    if 'file_delete' in changes:
        shared_file_delete(changes['file_delete'],last_sync_str)
    if 'user_removed' in changes:
        shared_file_delete(changes['user_removed'],last_sync_str)

def handle_sharefile(msg,username):
    print ('sharefile was modified by client')
    raw_data=base64.b64decode(msg['data']).decode('utf-8')
    sharefile_new=parse_sharefile(raw_data)
    selectfile=get_selectfile(username)
    if check_membership_sharefiles(username):
        sharefile_old=get_sharefiles(username)
        changes=get_changes_sharefile(sharefile_new,sharefile_old,selectfile)
        handle_sharefile_changes(changes,username,msg['last_sync'])
    else:
        # sharefiles[username]=sharefile_new
        set_sharefiles(username,sharefile_new)
        changes=get_changes_sharefile(sharefile_new,{},selectfile)
        handle_sharefile_changes(changes,username,msg['last_sync'])
    set_sharefiles(username,sharefile_new)

def parse_selectfile(selectfile_str):
    return selectfile_str.split('\n')

def get_selectfile(username):
    if check_membership_selectfiles(username):
        return get_selectfiles(username)
    else:
        return None

def get_changes_selectfile(selectfile_new,selectfile_old):
    changes={}
    changes['file_add']=list(set(selectfile_new) - set(selectfile_old))
    changes['file_delete']=list(set(selectfile_old) - set(selectfile_new))
    print ('changes in selectfile: ',changes)
    return changes
    

def handle_selectfile_changes(changes,sharefile,username,last_sync_str):
    # this will use selectfile to manage changes in shared files for other users
    changes_sharefile={}
    if 'file_add' in changes:
        files=changes['file_add']
        files_to_add_in_shared_users=[]
        for filename in files:
            if filename in sharefile:
                files_to_add_in_shared_users.append(filename)   
        if files_to_add_in_shared_users:     
            changes_sharefile['file_add']={k:v for k,v in sharefile.items() if k in files_to_add_in_shared_users}

    if 'file_delete' in changes:
        files=changes['file_delete']
        files_to_delete_in_shared_users=[]
        for filename in files:
            if filename in sharefile:
                files_to_delete_in_shared_users.append(filename)
        if files_to_delete_in_shared_users:
            changes_sharefile['file_delete']={k:v for k,v in sharefile.items() if k in files_to_delete_in_shared_users}

    print('sharefile',sharefile)
    print('changes_sharefile',changes_sharefile)
    if changes_sharefile:
        handle_sharefile_changes(changes_sharefile,username,last_sync_str)

def handle_selectfile(msg,username):
    print ('selectfile was modified by client')
    raw_data=base64.b64decode(msg['data']).decode('utf-8')
    selectfile_new=parse_selectfile(raw_data)
    if check_membership_selectfiles(username):
        selectfile_old=get_selectfiles(username)
        changes=get_changes_selectfile(selectfile_new,selectfile_old)
    else:
        changes=get_changes_selectfile(selectfile_new,{})
    if check_membership_sharefiles(username):
        sharefile=get_sharefiles(username)
        handle_selectfile_changes(changes,sharefile,username,msg['last_sync'])
    set_selectfiles(username,selectfile_new)
    print ('select file updated to: ',get_selectfiles(username))

def read_file(filename):
    if os.path.exists(filename):
        with open(filename, "rb") as file:
            data = file.read().decode('utf-8')
            return data
    else:
        return None

def load_configuration_files(username):
    sharefile_path=os.path.join(os.getcwd(),username,'Sharefile.dropbin')
    sharefile_str=read_file(sharefile_path)
    # print('sharefile_str',sharefile_str)
    if sharefile_str:
        sharefile=parse_sharefile(sharefile_str)
        print('sharefile loaded from file',sharefile)
        print('testing',username,sharefile)
        set_sharefiles(username,sharefile)
        print('sharefile',get_sharefiles(username))
        # sharefiles[username]=sharefile

    selectfile_path=os.path.join(os.getcwd(),username,'Selectfile.dropbin')
    selectfile_str=read_file(selectfile_path)
    if selectfile_str:
        selectfile=parse_selectfile(selectfile_str)
        print('selectfile loaded from file',selectfile)
        set_selectfiles(username,selectfile)
        print('selectfile',get_selectfiles(username))
        # selectfiles[username]=selectfile    
    # print (sharefiles,selectfiles)
    print ('configuration files loaded successfully')
        
def delete_from_collaborators(filename,username):
    sharefile=get_sharefiles(username)
    if filename in sharefile:
        # shared_file_delete(changes,last_sync_str):
        changes={}
        changes[filename]=sharefile[filename]
        shared_file_delete(changes,str(datetime.datetime.now()))

def handle_client(conn,junk):
    client_dir=None
    username=None
    while True:
        if check_active()==False:
            break
        # print ("username",username)
        # print ("sharefiles",sharefiles)

        # print ("waiting for client message")
        msg = get_message(conn)
        if msg['type'] == 'file_upload':
            print('file added ', os.path.join(client_dir, msg['filename']))
            if msg['filename']=='Sharefile.dropbin':
                handle_sharefile(msg,username)
            if msg['filename']=='Selectfile.dropbin':
                handle_selectfile(msg,username)
            add_file(client_dir, msg['filename'], msg['data'],msg['modified_date'])
            handle_shared_clients(username,msg['filename'],msg['last_sync'])
        elif msg['type'] == 'file_delete':
            print('file deleted ', os.path.join(client_dir, msg['filename']))
            delete_file(client_dir, msg['filename'])
            delete_from_collaborators(msg['filename'],username)
        elif msg['type'] == 'username':
            print ('user connecting: ', msg['username'])
            client_dir=get_user_dir(msg['username'])
            username=msg['username']
            load_configuration_files(username)
        elif msg['type'] == 'get_file_list':
            send_file_list(conn,client_dir)
        elif msg['type'] == 'download_from_server':
            print ('sending file to client: ',msg['filename'])
            send_file(conn,os.path.join(client_dir,msg['filename']))
        elif msg['type'] == 'last_sync':
            store_last_sync(username,msg['last_sync'])
            if not sharefile_changes_queue.empty():
                print ('Queue: ',sharefile_changes_queue)
                shared_file_add(sharefile_changes_queue.get(),username,msg['last_sync'])
        elif msg['type'] == 'get_last_sync':
            send_last_sync(conn,username)

    print ("Client disconnected or server shutting down")
    conn.close()

def check_active():
    return Active

def set_active():
    global Active
    while True:
        end=input('Enter end to exit server: \n')
        if end=='end':
            Active=False
            print('active was set to false')
            break


def write_last_sync_to_file():
    # path=os.path.join(os.getcwd(),'last_sync.dropbin')
    # write_file(path,last_sync)
    if last_sync:
        add_file(os.getcwd(),'last_sync.dropbin',last_sync)

def server(port):
    host = socket.gethostbyname(socket.gethostname())

    s = socket.socket()
    s.bind((host, port))
    s.listen(10)
    threading.Thread(target=set_active, args=() ).start()
    print("Host ", host, " is listening on ", port)
    s.settimeout(2)
    while True:
        count=threading.active_count()
        # print(count,check_active())
        if count==1 and check_active()==False:
            print('breaking from server short loop')
            break
        try:
            conn, addr = s.accept()
        except socket.timeout:
            # print ('connection timed out')
            continue
        print("Got connection form ", addr)
        threading.Thread(target=handle_client, args=(conn,'junk') ).start()
        
    write_last_sync_to_file()
    print("server shutting down")
    s.close()
        
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("port", type=int, help="Port number the server will listen on.")
    args = parser.parse_args()
    server(args.port)
    