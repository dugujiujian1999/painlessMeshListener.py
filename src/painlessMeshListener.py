#!/usr/bin/env python3

import asyncio
import json
import logging
import random
from asyncio import StreamReader, StreamWriter


# Function to establish a TCP connection
async def connect_tcp(host, port, on_connect):
    try:
        reader, writer = await asyncio.open_connection(host, port)
        await on_connect(reader, writer)
    except Exception as e:
        logging.error(f"Unable to connect to TCPServer: {e}")


# Node class representing a node in the network
class Node:
    def __init__(self):
        self.node_id = None
        self.connections = {}
        self.receive_callback = None

    # Periodic maintenance task to check for unused connections
    async def init_maintenance(self):
        while True:
            curr_time = asyncio.get_running_loop().time()
            logging.debug("Checking for unused connections")
            for from_id, conn in self.connections.items():
                await self.send_node_sync(from_id)
                if curr_time - conn.last_received > 60:
                    await self.remove_connection(from_id)
            await asyncio.sleep(6)

    # Handler for new connections
    async def init_connection(self, reader: StreamReader, writer: StreamWriter):
        logging.debug("New connection")
        from_id = 0
        try:
            while not reader.at_eof():
                data = await reader.readuntil(b"\0")
                json_data = json.loads(data[:-1])
                logging.debug(f"Received message: {json_data}")
                if from_id == 0 and json_data["type"] in [
                    PackageType.TIME_SYNC,
                    PackageType.NODE_SYNC_REQUEST,
                    PackageType.NODE_SYNC_REPLY,
                ]:
                    from_id = json_data["from"]
                    self.connections[from_id] = Connection(writer, from_id)

                if from_id in self.connections:
                    self.connections[from_id].last_received = (
                        asyncio.get_running_loop().time()
                    )

                await self.handle_message(from_id, json_data)
        except Exception as e:
            logging.error(f"Failed to read from client: {e}")
        await self.remove_connection(from_id)

    # Initialize the server and start listening for connections
    async def init_server(self, port):
        server = await asyncio.start_server(self.init_connection, port=port)
        asyncio.create_task(self.init_maintenance())
        async with server:
            await server.serve_forever()

    # Initialize the client and connect to the specified address
    async def init_client(self, addr):
        while True:
            try:
                logging.debug(f"Trying to connect to: {addr}")
                await connect_tcp(addr[0], addr[1], self.init_connection)
                break
            except Exception as e:
                logging.debug(f"Unable to connect to: {addr}. Retrying in 10 seconds")
                await asyncio.sleep(10)
        asyncio.create_task(self.init_maintenance())

    # Set the receive callback function
    def on_receive(self, callback):
        self.receive_callback = callback

    # Send a single message to a specific destination
    async def send_single(self, dest, msg):
        pack = {
            "dest": dest,
            "from": self.node_id,
            "type": PackageType.SINGLE,
            "msg": msg,
        }
        for k, v in self.connections.items():
            if v.contains_id(dest):
                await self.safe_write(k, json.dumps(pack))
                return True
        return False

    # Send a broadcast message to all connected nodes
    async def send_broadcast(self, msg):
        pack = {
            "dest": 0,
            "from": self.node_id,
            "type": PackageType.BROADCAST,
            "msg": msg,
        }
        for k, v in self.connections.items():
            logging.debug(f"sendBroadcast: send message to {k}")
            await self.safe_write(k, json.dumps(pack))
        return True

    # Safely write data to a connection
    async def safe_write(self, connection_id, pkge):
        logging.debug(f"Send to {connection_id}, msg {pkge}")
        try:
            if connection_id in self.connections:
                writer = self.connections[connection_id].writer
                writer.write(pkge.encode())
                writer.write(b"\0")
                await writer.drain()
                return True
            else:
                return False
        except Exception as e:
            await self.remove_connection(connection_id)
            logging.error(f"Failed to write to client: {e}")
            return False

    # Remove a connection from the node
    async def remove_connection(self, conn_id):
        if conn_id in self.connections:
            logging.debug(f"Removing connection {conn_id}")
            writer = self.connections[conn_id].writer
            writer.close()
            await writer.wait_closed()
            del self.connections[conn_id]
            for other_id in self.connections.keys():
                await self.send_node_sync(other_id, True)
            return True
        else:
            return False

    # Handle incoming messages based on their type
    async def handle_message(self, from_id, json_data):
        if from_id not in self.connections:
            logging.debug("Unknown nodeId")
            return False
        if json_data["type"] in [
            PackageType.NODE_SYNC_REQUEST,
            PackageType.NODE_SYNC_REPLY,
        ]:
            self.connections[from_id].subs = [
                SubConnection(**sub) for sub in json_data["subs"]
            ]
            if json_data["type"] == PackageType.NODE_SYNC_REQUEST:
                await self.send_node_sync(from_id, False)
        elif json_data["type"] == PackageType.TIME_SYNC:
            time_received = node_time()
            ts = TimeSync(**json_data["msg"])
            if ts.type != 2:
                pack = {
                    "dest": from_id,
                    "from": self.node_id,
                    "type": PackageType.TIME_SYNC,
                }
                if ts.type == 0:
                    ts.t0 = node_time()
                elif ts.type == 1:
                    ts.t1 = time_received
                    ts.t2 = node_time()
                ts.type += 1
                pack["msg"] = ts.__dict__
                await self.safe_write(from_id, json.dumps(pack))
            else:
                global adjust_time
                adjust_time += (ts.t1 - ts.t0) / 2 + (ts.t2 - time_received) / 2
        elif json_data["type"] == PackageType.BROADCAST:
            for k, v in self.connections.items():
                if not v.contains_id(from_id):
                    await self.safe_write(k, json.dumps(json_data))
            if self.receive_callback:
                await self.receive_callback(json_data["from"], json_data["msg"])
        elif json_data["type"] == PackageType.SINGLE:
            dest = json_data["dest"]
            if self.receive_callback and dest == self.node_id:
                await self.receive_callback(json_data["from"], json_data["msg"])
            else:
                for k, v in self.connections.items():
                    if v.contains_id(dest):
                        await self.safe_write(k, json.dumps(json_data))
                        break
        return True

    # Send a node synchronization request or reply
    async def send_node_sync(self, from_id, request=True):
        if from_id in self.connections:
            pack = {
                "dest": from_id,
                "from": self.node_id,
                "type": (
                    PackageType.NODE_SYNC_REQUEST
                    if request
                    else PackageType.NODE_SYNC_REPLY
                ),
                "subs": [
                    {"nodeId": v.node_id, "subs": v.subs}
                    for k, v in self.connections.items()
                    if k != from_id
                ],
            }
            await self.safe_write(from_id, json.dumps(pack))
        else:
            logging.debug("Connection not found during node sync")


# Connection class representing a connection to another node
class Connection:
    def __init__(self, writer, node_id):
        self.writer = writer
        self.node_id = node_id
        self.subs = []
        self.last_received = asyncio.get_running_loop().time()

    # Check if the connection contains a specific node ID
    def contains_id(self, id):
        if self.node_id == id:
            return True
        elif not self.subs:
            return False
        else:
            return any(sub.contains_id(id) for sub in self.subs)


# SubConnection class representing a sub-connection within a connection
class SubConnection:
    def __init__(self, nodeId, subs=None):
        self.node_id = nodeId
        self.subs = subs or []

    # Check if the sub-connection contains a specific node ID
    def contains_id(self, id):
        if self.node_id == id:
            return True
        else:
            return any(sub.contains_id(id) for sub in self.subs)


# PackageType class defining different types of packages
class PackageType:
    DROP = 3
    TIME_SYNC = 4
    NODE_SYNC_REQUEST = 5
    NODE_SYNC_REPLY = 6
    BROADCAST = 8  # application data for everyone
    SINGLE = 9  # application data for a single node


# TimeSync class representing time synchronization data
class TimeSync:
    def __init__(self, type=0, t0=0, t1=0, t2=0):
        self.type = type
        self.t0 = t0
        self.t1 = t1
        self.t2 = t2


# Global variable to store time adjustment
adjust_time = 0


# Function to get the current node time
def node_time():
    return int((asyncio.get_running_loop().time() + adjust_time) * 1e6)


# Default port for the node
port = 5555
node = None


# Main function to initialize and run the node
async def main():
    global node
    node = Node()
    node.node_id = random.randint(0, 2**32 - 1)

    # Callback function to handle received messages
    async def on_receive(source, msg):
        print(msg)

    node.on_receive(on_receive)

    # Task to periodically send broadcast messages
    async def send_task():
        while True:
            msg = {"action": "logNode", "nodeId": node.node_id}
            await node.send_broadcast(json.dumps(msg))
            await asyncio.sleep(1)

    asyncio.create_task(send_task())

    ##
    ## IP address of the node to connect to (if any)
    ## TODO: Refrain from using a hard-coded IP address;
    ##       utilize argparse for selection or implement automatic detection.
    ##
    ip = "10.254.165.1"
    if ip:
        addr = (ip, port)
        await node.init_client(addr)
    else:
        await node.init_server(port)


if __name__ == "__main__":
    asyncio.run(main())
