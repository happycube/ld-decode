#!/usr/bin/python

from pyfann import libfann
import sys

connection_rate = 2
learning_rate = 0.05
num_input = 27
num_hidden = 3
num_output = 2

desired_error = 0.00001
#desired_error = 0.00031 
#desired_error = 0.00057
max_iterations = 500
iterations_between_reports = 10

ann = libfann.neural_net()
ann.create_sparse_array(connection_rate, (num_input, num_hidden, num_output))
ann.set_learning_rate(learning_rate)
ann.set_activation_function_output(libfann.SIGMOID_SYMMETRIC_STEPWISE)

ann.train_on_file(sys.argv[1], max_iterations, iterations_between_reports, desired_error)

ann.print_connections();

ann.save("test.net")
