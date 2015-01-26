#!python3

efm_in = open("efm-map")
print("unsigned short int efm[] {");
for i in range(0, 256):
	inline = efm_in.readline()
	print("    0b", inline[0:len(inline)-1], ",",  sep="")

print("};")
print("")
