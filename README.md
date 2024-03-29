# PainlessMeshListener.py

This Python script is a tiny replacement for the [PainlessMeshListener](https://gitlab.com/painlessMesh/painlessMeshListener) functionality.    
It implements a distributed network of nodes that can communicate with each other using TCP connections. The nodes can send and receive messages, perform time synchronization, and maintain a list of connected nodes.  

## Features

- Establishes TCP connections between nodes
- Handles incoming connections and messages
- Supports different types of messages: single, broadcast, time sync, node sync request/reply
- Performs periodic maintenance to check for unused connections
- Allows setting a receive callback function to handle incoming messages
- Sends periodic broadcast messages to all connected nodes
- Supports connecting to a specific node or running as a server

## Usage

1. Make sure you have Python 3.4 or higher installed.
2. Change the script.
3. Enjoy.

## Warnning

This project is currently for experimental purposes only and has not undergone comprehensive testing.