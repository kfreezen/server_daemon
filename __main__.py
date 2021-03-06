import socket
import errno
import time
import sys
import threading

import re

import logging

import datetime

import MySQLdb as mdb
import constants
from constants import DB_Connect

constants.initConstants()

VERSION = 1

logging.basicConfig(level=logging.INFO)

TCP_IP = '0.0.0.0'
TCP_PORT = 14440
BUFFER_SIZE = 1024
MAX_BACKLOG = 16

HEARTBEAT_TIMEOUT = 20.0
ONCONNECT_TIMEOUT = 5.0

QUIT = 255

class RSCPContent(object):
	def __init__(self):
		self.request = ""
		self.data = dict()

	def loadFromString(self, str):
		self.clear()

		lines = str.split("\n")
		lineItr = 0
		for line in lines:
			if lineItr == 0: # request line.
				self.request = line
			else:
				pattern = re.compile(":\s*")
				strElems = pattern.split(line)
				if len(strElems) < 2:
					pass # Invalid, we should handle an error, if it is.
				else:
					self.data[strElems[0]] = strElems[1]

			lineItr += 1

	def generateString(self):
		theString = ""

		theString += self.request + "\n"
		for key in self.data:
			theString += key + ": " + self.data[key] + "\n"

		theString += "\n"
		return theString

	def clear(self):
		self.data.clear()
		self.request = ""

class ClientSocket(object):
	def __init__(self, sock):
		self.socket = sock
		self.lastHeartbeat = time.time()
		self.buffer = ""
		self.isDisconnected = True # It is disconnected until heartbeat handled for the first time.
		self.disconnectCause = ""
		self.id = ""
		self.version = 0

	def sendContent(self, content):
		self.socket.send(content.generateString())

	def getPacket(self, tmo=0):
		time_left = tmo
		while time_left > 0 and tmo > 0:
			self.getDataFromSocket()
			if self.checkForEndOfContent():
				return self.getContent()
			else:
				time.sleep(0.10)
				time_left -= 0.10

		return False

	# This gets all available data from the socket and appends it to self.buffer
	def getDataFromSocket(self):
		try:
			tryData = self.socket.recv(BUFFER_SIZE)
			
			# We are on a nonblocking socket.
			# 0 length data without errors would indicate that the other endpoint has been
			# disconnected, most likely through software action.
			if len(tryData) == 0:
				self.setDisconnected(True)
				
			self.buffer += tryData
			
		except socket.error, e:
			err = e.args[0]
			if err == errno.EAGAIN or err == errno.EWOULDBLOCK:
				pass
			elif err == errno.EPIPE or err == errno.ECONNRESET:
				self.setDisconnected(True)
			else:
				print 'baderr', err
				# TODO:  Improve the error handling.
			
	def checkForEndOfContent(self):
		if len(self.buffer) < 2:
			return False # End of content indicator is 2 bytes long.

		if self.buffer[len(self.buffer)-2] == "\n" and self.buffer[len(self.buffer)-1] == "\n":
			return True
		else:
			return False

	def getContent(self):
		if self.checkForEndOfContent():
			dataStr = self.buffer
			self.buffer = ""
			content = RSCPContent()
			content.loadFromString(dataStr)
			return content
	
	def handleHeartbeat(self, mysql, heartbeatTime):
		cur = mysql.cursor(mdb.cursors.DictCursor)
		
		print "handling heartbeat."

		if self.isDisconnected:
			self.isDisconnected = False
			
			with mysql:
				cur.execute("""INSERT INTO receivers_online
					(`receiver_id`, `event`, `date_logged`)
					VALUES (%s, %s, %s)
				""", (self.id, "online", long(time.time())))
		
		self.lastHeartbeat = time.time()

		cur.close()

	def send(self, data):
		while True:
			try:
				self.socket.send(data)

				# We want to try again if the send failed for some reason
				# This break is never reached if something goes wrong with send.
				break
			except socket.error, e:
				err = e.args[0]
				if err == errno.EAGAIN or err == errno.EWOULDBLOCK:
					time.sleep(0.1)
					continue
				elif err == errno.EPIPE or err == errno.EBADF:
					self.setDisconnected(True)
					self.close()
					break
				else:
					raise e
	
	def setDisconnected(self, disconnected):
		global mysql
			
		if disconnected and not self.isDisconnected:
			self.isDisconnected = disconnected

			try:
				mysql.ping(True)
			except:
				print 'something happened with ping.  ignoring.'

			cur = mysql.cursor(mdb.cursors.DictCursor)

			with mysql: # Notify the database that the receiver is now offline.
				cur.execute("""INSERT INTO `receivers_online`
					(`receiver_id`, `event`, `date_logged`)
					VALUES (%s, %s, %s)
				""", (self.id, "offline", long(time.time())))
			
			cur.close()

	def close(self):
		self.socket.close()

clientSockets = []

threadComms = []

mysql = DB_Connect()

def ClientSocketCommunicatorThread(threadNum):
	global threadComms
	global clientSockets
	global mysql

	# We want to go through these sockets once every 100 ms.

	while threadComms[threadNum] != QUIT:

		startTime = time.time()
		for sockData in clientSockets:
			if not sockData.isDisconnected:
				sockData.getDataFromSocket()
			
			if sockData.checkForEndOfContent():
				content = sockData.getContent()

				print "handling", content.request

				# Handle the content.
				if content.request == "HEARTBEAT":
					# heartbeat!
					logging.debug("heartbeat " + str(sockData.id))
					sockData.handleHeartbeat(mysql, time.time())

					#sockData.lastHeartbeat = time.time()
					#sockData.isDisconnected = False
				elif content.request == "LOG":
					# log request!

					# We should store it in a log file, for now.
					logfile = open('receiverslog', 'a')

					# format the headers.
					server_timestamp = time.time()
					receiver_timestamp = long(content.data["timestamp"])
					_date = datetime.datetime.fromtimestamp(server_timestamp)
					strToLog = ""
					strToLog += _date.strftime('%Y-%m-%d %H:%M:%S')

					if receiver_timestamp != 0:
						difference = long(server_timestamp - receiver_timestamp)
						if difference != 0:
							strToLog += " r%c%d" % ( '-' if difference < 0 else '+', abs(difference))

					strToLog += ": %s:" % (sockData.id)
					strToLog += " %s\n" % (content.data["message"])
					logfile.write(strToLog)

					logfile.close()

			# Do a heartbeat check on this socket.
			if not sockData.isDisconnected and sockData.lastHeartbeat + HEARTBEAT_TIMEOUT < time.time():
				sockData.send("HEARTBEAT\n\n")

				# TODO Implement some sort of SIGPIPE handler or something here.

		endTime = time.time()
		if endTime < startTime + 0.1:
			time.sleep(0.1 - (endTime - startTime))


try: # This try-except-finally is to catch any previously uncaught exceptions, so that we can have clean exit.
	# Bind the server socket.
	serverSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	serverSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

	serverSocket.bind((TCP_IP, TCP_PORT))
	serverSocket.listen(MAX_BACKLOG)

	threadComms.append(0)
	clientCommThread = threading.Thread(target=ClientSocketCommunicatorThread, args=(len(threadComms) - 1,))
	clientCommThread.start()

	# Server socket loop
	while 1:
		_sock, addr = serverSocket.accept()
		print 'addr =', addr

		_sock.setblocking(0)
		clientSocket = ClientSocket(_sock)

		data = clientSocket.getPacket(ONCONNECT_TIMEOUT)
		if data == False:
			continue

		print 'gotData'

		if data.request == "CONNECT":
			if 'id' not in data.data:
				# Invalid connection.
				clientSocket.close()
				continue
			else:
				# Search for ID already existing in client sockets.
				clientSocket.id = long(data.data['id'])
				clientSocket.handleHeartbeat(mysql, time.time())
				
				replacedClientSocket = False
				for (i, sockData) in enumerate(clientSockets):
					if sockData.id == clientSocket.id:
						sockData.close()
						clientSockets[i] = clientSocket
						replacedClientSocket = True

				if not replacedClientSocket:
					clientSockets.append(clientSocket)

			if 'version' not in data.data:
				clientSocket.version = 0
			else:
				clientSocket.version = int(data.data['version'])

			connectSuccess = RSCPContent()
			connectSuccess.request = "CONNECT"
			connectSuccess.data["ack"] = "success"
			clientSocket.sendContent(connectSuccess)
			print 'sentData'
		else:
			# Invalid connection
			clientSocket.close()
			continue


		clientSockets.append(clientSocket)
except Exception, e:
	logging.exception(str(e))

finally:
	for i in threadComms:
		threadComms[i] = QUIT

	serverSocket.close()

	for sock in clientSockets:
		sock.close()

	sys.exit(0)
