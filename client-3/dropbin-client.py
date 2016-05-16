import argparse
import sys
import argparse
import socket
import os
import time
import base64
import json
import datetime

def send_msg(conn, msg):
    serialized = json.dumps(msg).encode('utf-8')
    conn.send(b'%d\n' % len(serialized))
    conn.sendall(serialized)

# copied from server
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

def get_file_list(client_dir):
    files = os.listdir(client_dir)
    files = [file for file in files if os.path.isfile(os.path.join(client_dir, file))]
    file_list = {}
    for file in files:
        path = os.path.join(client_dir, file)
        mtime = os.path.getmtime(path)
        # ctime = os.path.getctime(path)
        file_list[file] = mtime

    return file_list

def filter_select_file(client_dir,file_list_all):
    # filer this file_list by only keeping files in Selectfile.dropbin
    select_files=[]
    select_file=os.path.join(client_dir,'Selectfile.dropbin')
    if (os.path.exists(select_file)):
        with open(select_file) as file:
            for line in file:
                select_files.append(line.rstrip())
        return {k:v for k,v in file_list_all.items() if k in select_files}
        
    return file_list_all

def get_file_list_from_server(conn):
    msg={
        'type' : 'get_file_list'
    }
    send_msg(conn,msg)
    return get_message(conn)

def check_configuartion_file_changes(filename,server_file_list,file_list_all,changes):
    if filename in server_file_list:
        if filename in file_list_all:
            if server_file_list[filename] > file_list_all[filename]:
                changes[filename]='file_download_from_server'
            elif server_file_list[filename] < file_list_all[filename]:
                changes[filename]='file_upload_to_server'
        else:
            changes[filename]='file_download_from_server'
        if filename in changes:
            print ('configuration file: %s changed' % filename)
    elif filename in file_list_all:
        changes[filename]='file_upload_to_server'
    return changes

def set_difference(dict_a,dict_b):
    return {k:v for k,v in dict_a.items() if k not in dict_b}

def get_server_last_sync(conn):
    msg={
        'type' : 'get_last_sync'
    }
    send_msg(conn,msg)
    reply=get_message(conn)
    if reply['last_sync']=='min':
        return datetime.datetime.min
    else:
        return datetime.datetime.strptime(reply['last_sync'], "%Y-%m-%d %H:%M:%S.%f")

def send_last_sync(conn,date):
    msg={
        'type' : 'last_sync',
        'last_sync' : str(date)
    }
    send_msg(conn,msg)

def get_changes(conn, client_dir, last_file_list,last_sync):
    server_file_list=get_file_list_from_server(conn)    
    file_list_all = get_file_list(client_dir)
    changes = {}
    # getting priority changes files
    check_configuartion_file_changes('Selectfile.dropbin',server_file_list,file_list_all,changes)
    check_configuartion_file_changes('Sharefile.dropbin',server_file_list,file_list_all,changes) 

    print('last_file_list',last_file_list)
    print ('server_file_list ',server_file_list)
    print('file_list_all ',file_list_all)
    selected_files=None
    if 'Selectfile.dropbin' not in changes:
        selected_files=filter_select_file(client_dir,file_list_all)
        
        files_to_delete_from_server=set_difference(last_file_list,selected_files)
        for filename in files_to_delete_from_server:
            changes[filename]='file_delete_from_server' 
            
        server_files_filtered= set_difference(server_file_list,files_to_delete_from_server)
        server_last_sync=get_server_last_sync(conn)

        
        print ('client last sync',last_sync)
        print ('server last_sync ',server_last_sync)

        files_to_delete_from_client={}
        if last_sync > server_last_sync:
            files_to_delete_from_client = set_difference(selected_files,server_files_filtered)
            for filename in files_to_delete_from_client:
                changes[filename]='file_delete_from_client'

        remaining_files_on_client=set_difference(selected_files,files_to_delete_from_client)
        # if last_sync < server_last_sync:
        for filename in remaining_files_on_client:
            if filename not in server_files_filtered or selected_files[filename] > server_file_list[filename]:
                changes[filename]='file_upload_to_server'

        for filename in server_files_filtered:
            if (filename not in file_list_all or server_files_filtered[filename] > file_list_all[filename]) and filename not in files_to_delete_from_server:
                changes[filename]='file_download_from_server'    
        
         
        print ('selected_files',selected_files)
        print ('files_to_delete_from_server',files_to_delete_from_server)
        print ('server_files_filtered',server_files_filtered)
        print('files_to_be_deleted_from_client',files_to_delete_from_client)
        print('remaining_files_on_client',remaining_files_on_client)

    print ('======CHANGES======: ',changes)
    last_sync=datetime.datetime.now()
    if selected_files is None:
        selected_files=last_file_list
    return (changes, selected_files,last_sync)

def download_from_server(conn,filename):
    msg={
        'type' : 'download_from_server',
        'filename' : filename
    }
    send_msg(conn,msg)
    reply=get_message(conn)
    path = os.path.join(os.getcwd(), filename)
    with open(path, 'wb') as file:
        file.write(base64.b64decode(reply['data'].encode('utf-8')))
    os.utime(path,(0,reply['modified_date']))

def send_new_file(conn, filename,last_sync):
    with open(filename, "rb") as file:
        data = base64.b64encode(file.read()).decode('utf-8')
        msg = {
            'type': 'file_upload',
            'filename': filename,
            'data': data,
            'modified_date' : os.path.getmtime(filename)
            # 'last_sync' : str(last_sync)
        }
        # if filename=='Sharefile.dropbin' or filename == 'Selectfile.dropbin':
        msg['last_sync']=str(last_sync)
        send_msg(conn, msg)

def send_delete_file(conn, filename):
    msg = {
        'type': 'file_delete',
        'filename': filename
    }
    send_msg(conn, msg)

def delete_from_client(filename):
    path = os.path.join(os.getcwd(), filename)
    if os.path.exists(path):
        os.remove(path)

def handle_dir_change(conn, changes,last_sync):
    for filename, change in changes.items():
        if change == 'file_upload_to_server':
            print('file uploaded to server ', filename)
            send_new_file(conn, filename,last_sync)
        elif change == 'file_delete_from_server':
            print('file deleted ', filename)
            send_delete_file(conn, filename)
        elif change == 'file_delete_from_client':
            print ('deleting file from client')
            delete_from_client(filename)
        elif change == 'file_download_from_server':
            print ('downloading from server: ',filename)
            download_from_server(conn,filename)
    send_last_sync(conn,last_sync)



def watch_dir(conn, client_dir, handler):
    last_file_list = {}
    last_sync=datetime.datetime.min
    # main client loop
    while True:
        print('---------------CLIENT LOOP --------------------')
        time.sleep(2)
        changes, last_file_list,last_sync = get_changes(conn, client_dir, last_file_list,last_sync)
        handler(conn, changes,last_sync)

def client(server_addr, server_port, client_dir, username):
    s = socket.socket()
    s.connect((server_addr, server_port))
    msg= {
        'type': 'username',
        'username': username
    }
    send_msg(s,msg)
    watch_dir(s, client_dir, handle_dir_change)
    s.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("server_addr", help="Address of the server.")
    parser.add_argument("server_port", type=int, help="Port number the server is listening on.")
    parser.add_argument("username", help="Username of the client")
    args = parser.parse_args()
    client(args.server_addr, args.server_port, os.getcwd(),args.username)