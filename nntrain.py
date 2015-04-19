#!/usr/bin/python

from pyfann import libfann
import sys

connection_rate = 1.0 
learning_rate = 0.25
num_input = 16 
num_hidden = 32 
num_output = 2

desired_error = 0.000052 
#desired_error = 0.00031 
#desired_error = 0.00057
max_iterations = 100
iterations_between_reports = 10

ann = libfann.neural_net()
ann.create_sparse_array(connection_rate, (num_input, num_hidden, num_output))
ann.set_learning_rate(learning_rate)
#ann.set_activation_function_hidden(libfann.SIGMOID_SYMMETRIC_STEPWISE)
#ann.set_activation_function_hidden(libfann.SIGMOID_SYMMETRIC)
#ann.set_activation_function_output(libfann.SIGMOID_SYMMETRIC_STEPWISE)
#for i in range(16,32):
#	ann.set_activation_function(libfann.LINEAR_PIECE_SYMMETRIC, 1, i)

ann.set_activation_function_hidden(libfann.LINEAR_PIECE_SYMMETRIC)
ann.set_activation_function_output(libfann.LINEAR_PIECE_SYMMETRIC)
#ann.set_activation_function_output(libfann.SIN_SYMMETRIC)
#ann.set_activation_function_output(libfann.LINEAR)

train_data = libfann.training_data()
for i in range(1, len(sys.argv)):
	print sys.argv[i]
	train_data.read_train_from_file(sys.argv[i])

ann.train_on_data(train_data, max_iterations, iterations_between_reports, desired_error)

ann.print_connections();

ann.save("test.net")

for i in range(1, len(sys.argv)):
	print sys.argv[i]
	test_data = libfann.training_data()
	test_data.read_train_from_file(sys.argv[i])
	ann.test_data(test_data)
	print ann.get_MSE()
