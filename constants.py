#mysql_host = "localhost"
#mysql_user = "tempsensor_user"
#mysql_pass = "ZYMeGZcVhKHwakt"
#mysql_db = "tempsensor_web"
encryption = "sha512"
REPORTS_NUM = 5
GLOBAL_SCOPE = "global"
NETWORK_SCOPE = "network"
SENSOR_SCOPE = "sensor"

#email_username = 'autofrostalarm@gmail.com'
#email_password = '3BfU77bJu6cVmBLTbKBMvWR3'

import MySQLdb as mdb

NUM_CONNECT_TRIES = 10

def DB_Connect(recurse=0):
	try:
		mysql = mdb.connect(host=mysql_host, port=int(mysql_port), user=mysql_user, passwd=mysql_pass, db=mysql_db)
	except mdb.OperationalError, e:
		if recurse > NUM_CONNECT_TRIES:
			raise e
		else:
			return DB_Connect(recurse+1)

	return mysql

#globals()[name] = value
def initConstants():
	constantsFile = open('constants', 'r')

	for line in constantsFile:
		line = line.strip()
		arr = line.split(' ')
		globals()[arr[0]] = arr[1]
