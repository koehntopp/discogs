from pymodbus.client import ModbusTcpClient as ModbusClient


client = ModbusClient('192.168.1.10', port=502)

client.connect()


if client.connect():
   try:
      APPD = client.read_holding_registers(40125, 1, 1)
      print (APPD.registers[0])
   except(ModbusIOException):
      print(ModbusIOException)


   