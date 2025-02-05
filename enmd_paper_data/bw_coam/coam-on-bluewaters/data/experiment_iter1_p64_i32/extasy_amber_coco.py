#!/usr/bin/env python

__author__        = "The ExTASY project"
__copyright__     = "Copyright 2013-2016, http://www.extasy-project.org"
__license__       = "MIT"
__use_case_name__ = "Amber + CoCo' simulation-analysis (ExTASY)."


from radical.ensemblemd import Kernel
from radical.ensemblemd import EnsemblemdError
from radical.ensemblemd import SimulationAnalysisLoop
from radical.ensemblemd import SingleClusterEnvironment
from radical.ensemblemd.engine import get_engine
import imp
import argparse
import sys
import os
import json

# ------------------------------------------------------------------------------
# Set default verbosity

if os.environ.get('RADICAL_ENMD_VERBOSE') == None:
    os.environ['RADICAL_ENMD_VERBOSE'] = 'REPORT'

# ------------------------------------------------------------------------------
#Load all custom Kernels

from kernel_defs.amber import kernel_amber
get_engine().add_kernel_plugin(kernel_amber)

from kernel_defs.coco import kernel_coco
get_engine().add_kernel_plugin(kernel_coco)


# ------------------------------------------------------------------------------


# ------------------------------------------------------------------------------
#

class Extasy_CocoAmber_Static(SimulationAnalysisLoop):

    def __init__(self, maxiterations, simulation_instances, analysis_instances):
        SimulationAnalysisLoop.__init__(self, maxiterations, simulation_instances, analysis_instances)

    def pre_loop(self):
        pass


    def simulation_step(self, iteration, instance):
        '''
        function : if iteration = 1, use .crd file from pre_loop, else use .crd output from analysis generated
        in the previous iteration. Perform amber on the .crd files to generate a set of .ncdf files.

        amber :-

                Purpose : Run amber on each of the coordinate files. Currently, a non-MPI version of Amber is used.
                            Generates a .ncdf file in each instance.

                Arguments : --mininfile = minimization filename
                            --mdinfile  = MD input filename
                            --topfile   = Topology filename and/or reference coordinates file filename
                            --cycle     = current iteration number
        '''
        k1 = Kernel(name="custom.amber")
        k1.arguments = ["--mininfile={0}".format(os.path.basename(Kconfig.minimization_input_file)),
                       "--topfile={0}".format(os.path.basename(Kconfig.top_file)),
                       "--crdfile={0}".format(os.path.basename(Kconfig.initial_crd_file)),
                       "--cycle=%s"%(iteration)]
        k1.link_input_data = ['$SHARED/{0}'.format(os.path.basename(Kconfig.minimization_input_file)),
                             '$SHARED/{0}'.format(os.path.basename(Kconfig.top_file)),
                             '$SHARED/{0}'.format(os.path.basename(Kconfig.initial_crd_file))]
        k1.cores = Kconfig.num_cores_per_sim_cu
        if((iteration-1)==0):
            k1.link_input_data = k1.link_input_data + ['$SHARED/{0} > min1.rst7'.format(os.path.basename(Kconfig.initial_crd_file))]
            k1.copy_output_data = ['min1.rst7 > $SHARED/md_{0}_{1}.rst'.format(iteration,instance)]
        else:
            k1.link_input_data = k1.link_input_data + ['$SHARED/min_{0}_{1}.rst7 > min{2}.rst7'.format(iteration-1,instance-1,iteration)]
            k1.copy_output_data = ['md{0}.rst > $SHARED/md_{0}_{1}.rst'.format(iteration,instance)]
        

        k2 = Kernel(name="custom.amber")
        k2.arguments = [
                            "--mdinfile={0}".format(os.path.basename(Kconfig.md_input_file)),
                            "--topfile={0}".format(os.path.basename(Kconfig.top_file)),
                            "--cycle=%s"%(iteration)
                
                        ]
        k2.link_input_data = [  
                                "$SHARED/{0}".format(os.path.basename(Kconfig.md_input_file)),
                                "$SHARED/{0}".format(os.path.basename(Kconfig.top_file)),
                                "$SHARED/md_{0}_{1}.rst > md{0}.rst".format(iteration,instance),
                            ]
	k2.cores = Kconfig.num_cores_per_sim_cu
        if(iteration%Kconfig.nsave==0):
            k2.download_output_data = ['md{0}.nc > output/iter{0}/md_{0}_{1}.nc'.format(iteration,instance)]

        return [k1,k2]


    def analysis_step(self, iteration, instance):
        '''
        function : Perform CoCo Analysis on the output of the simulation from the current iteration. Using the .ncdf
         files generated in all the instance, generate the .crd file to be used in the next simulation.

        coco :-

                Purpose : Runs CoCo analysis on a set of .ncdf files and generates a coordinate file.

                Arguments : --grid          = Number of points along each dimension of the CoCo histogram
                            --dims          = The number of projections to consider from the input pcz file
                            --frontpoints   = Number of CUs
                            --topfile       = Topology filename
                            --mdfile        = MD Input filename
                            --output        = Output filename
                            --cycle         = Current iteration number
        '''
        k1 = Kernel(name="custom.coco")
        k1.arguments = ["--grid={0}".format(Kconfig.grid),
                       "--dims={0}".format(Kconfig.dims),
                       "--frontpoints={0}".format(Kconfig.num_CUs),
                       "--topfile={0}".format(os.path.basename(Kconfig.top_file)),
                       "--mdfile=*.nc",
                       "--output=coco.rst7",
                       "--atom_selection={0}".format(Kconfig.atom_selection)]
        k1.cores = min(Kconfig.num_CUs,RPconfig.PILOTSIZE)
        k1.uses_mpi = True

        k1.link_input_data = ['$SHARED/{0}'.format(os.path.basename(Kconfig.top_file))]
        for iter in range(1,iteration+1):
            for i in range(1,Kconfig.num_CUs+1):
                k1.link_input_data = k1.link_input_data + ['$SIMULATION_ITERATION_{0}_INSTANCE_{1}/md{0}.nc > md_{0}_{1}.nc'.format(iter,i)]

        k1.copy_output_data = list()
        for i in range(0,Kconfig.num_CUs):
            k1.copy_output_data = k1.copy_output_data + ['coco{1}.rst7 > $SHARED/min_{0}_{1}.rst7'.format(iteration,i)]

        if(iteration%Kconfig.nsave==0):
            k1.download_output_data = ['coco.log > output/iter{0}/coco.log'.format(iteration,instance)]


        return k1

    def post_loop(self):
        pass


# ------------------------------------------------------------------------------
#
if __name__ == "__main__":

    try:

        parser = argparse.ArgumentParser()
        parser.add_argument('--RPconfig', help='link to Radical Pilot related configurations file')
        parser.add_argument('--Kconfig', help='link to Kernel configurations file')

        args = parser.parse_args()

        if args.RPconfig is None:
            parser.error('Please enter a RP configuration file')
            sys.exit(1)
        if args.Kconfig is None:
            parser.error('Please enter a Kernel configuration file')
            sys.exit(0)

        RPconfig = imp.load_source('RPconfig', args.RPconfig)
        Kconfig = imp.load_source('Kconfig', args.Kconfig)

        # Create a new static execution context with one resource and a fixed
        # number of cores and runtime.

        cluster = SingleClusterEnvironment(
            resource=RPconfig.REMOTE_HOST,
            cores=RPconfig.PILOTSIZE,
            walltime=RPconfig.WALLTIME,
            username = RPconfig.UNAME, #username
            project = RPconfig.ALLOCATION, #project
            queue = RPconfig.QUEUE,
            database_url = RPconfig.DBURL,
        #    access_schema = config[RPconfig.REMOTE_HOST]['schema']      # This is so to support different access methods - gsissh, ssh - remove this if always running using ssh
        )

        cluster.shared_data = [
                                Kconfig.initial_crd_file,
                                Kconfig.md_input_file,
                                Kconfig.minimization_input_file,
                                Kconfig.top_file,
                            ]

        cluster.allocate()

        coco_amber_static = Extasy_CocoAmber_Static(maxiterations=Kconfig.num_iterations, simulation_instances=Kconfig.num_CUs, analysis_instances=1)
        cluster.run(coco_amber_static)

        cluster.deallocate()

    except EnsemblemdError, er:

        print "Ensemble MD Toolkit Error: {0}".format(str(er))
        raise # Just raise the execption again to get the backtrace
