# standard packages
import os
import xslha
import shutil
import multiprocessing as mp

# modules of xBIT
import package.screen as screen
import package.debug  as debug

# ----------------------------------------------------------
# Class to run the different codes
# ----------------------------------------------------------


class HepTool:
    """Main class to run the different HEP tools"""

    def __init__(self, name, settings, runner, log):
        log.info('Class %s initialised' % name)
        self.name = name
        self.settings = settings
        self.runner = runner
        self.log = log

    def run(self, spc_file, temp_dir, log):
        log.info('Running %s ' % self.name)
        os.chdir(temp_dir)
        if os.path.exists(self.settings['Output']):
            if self.settings['Output'] is not self.settings['Input']:
                pass
                # os.remove(self.settings['Output'])
        self.runner(self.settings['Path'], self.settings['Binary'],
                    self.settings['Input'], self.settings['Output'],
                    spc_file, temp_dir, log)

# -----------------------------
#  Auxiliary Run and Parse functions for different codes
# -----------------------------


def RunSPheno(path, bin, input, output, spc_file, dir, log):
    debug.command_line_log(path + bin + " " + input, log)

class Runner():
    def __init__(self, scan, log):
        log.info('Initialise runner class. Number of cores: %s'
                 % str(scan.setup['Cores']))
        self.scan = scan

        self.all_valid = []
        self.all_invalid = []
        self.all_data = []

        # create temporary directories
        for x in range(scan.setup['Cores']):
            os.makedirs(os.path.join(scan.temp_dir, "id" + str(x)))

        # setup_loggers:
        self.loggers = [
            debug.new_logger(scan.debug, scan.curses, "id" + str(x),
                             os.path.join(scan.temp_dir, "id" + str(x))
                             + "/id" + str(x) + ".log")
            for x in range(scan.setup['Cores'])
        ]

    def run(self, log, sample=[]):
        if len(sample) < 1:
            self.all_parameter_variables = self.scan.generate_parameters(
                self.scan.variables, self.scan.setup['Points']
            )
        else:
            self.all_parameter_variables = sample

        # move points into queue in order to distribute work on several cores
        for x in self.all_parameter_variables:
            self.scan.all_points.put(x)

        if self.scan.setup['Cores'] > 1:
            self.multicore(log)
        else:
            self.singlecore(log)

    def multicore(self, log):
        # sample is not empty in case that the NN proposes the next points
        log.info('Starting multcore module. Number of cores: %s'
                 % str(self.scan.setup['Cores']))
        with mp.Manager() as manager:
            List_all = manager.list()
            List_valid = manager.list()
            List_invalid = manager.list()

            # define the processes and let them run
            processes = [mp.Process(
                target=self.run_all_points,
                args=(self.scan,
                      os.path.join(self.scan.temp_dir, "id" + str(x)),
                      x, self.loggers[x],
                      List_all, List_valid, List_invalid))
                for x in range(self.scan.setup['Cores'])]
            for p in processes:
                p.start()
            for p in processes:
                p.join()

            self.scan.all_data = self.scan.all_data + list(List_all)
            self.scan.all_valid = self.scan.all_valid + list(List_valid)
            self.scan.all_invalid = self.scan.all_invalid + list(List_invalid)

    def singlecore(self, log):
        self.run_all_points(self.scan,
                            os.path.join(self.scan.temp_dir, "id0"), 0,
                            self.loggers[0],
                            self.scan.all_data,
                            self.scan.all_valid,
                            self.scan.all_invalid
                            )

    # run points
    def run_all_points(self, scan, dir, nr, log, l1=None, l2=None, l3=None):
        log.info("Started with running the points")
        while not scan.all_points.empty():

            # 'progress-bar'
            if nr == 0:
                if scan.curses:
                    screen.update_count(scan.screen, scan.all_points.qsize(),
                                        scan.setup['Points'])
                else:
                    log.info("")
                    log.info("%i Points of %i Points left"
                             % (scan.all_points.qsize(), scan.setup['Points']))

            # running a point
            try:
                # in order to make sure that the last element
                # hasn't been 'stolen' in the meantime by another core
                point = scan.all_points.get()
                self.run_point(scan, point, dir, scan.output_file + str(nr),
                               l1, l2, l3, log)
            except:
                # break
                continue  # maybe, there was another problem than an empty queue?!
                          # let's try to continue instead of stopping

        if scan.curses:
            screen.update_count(scan.screen, 0, scan.setup['Points'])

    def bad_point_check(self, scan, log):
        if scan.setup['Interrupt'][0] == "True":
            values = []
            spc = xslha.read(scan.settings['SPheno']['Output'])
            for obs in scan.observables.values():
                try:
                    values.append(spc.Value(obs['SLHA'][0], obs['SLHA'][1]))
                except:
                    values.append(obs['MEAN'])
            if scan.likelihood(values) < scan.setup['Interrupt'][1]:  # likelihood too small
                log.info('Stopping further calculations for this point'
                         + ' because of bad likelihood')
                return True
            else:
                return False
        else:
            return False

    def run_point(self, scan, point, temp_dir, output_file,
                  list_all, list_valid, list_invalid, log):
        log.info('Running point with input parameters: %s'
                 % str(point))
        if scan.curses:
            screen.current_point_core(scan.screen, point, int(temp_dir[-1]))
        scan.write_lh_file(point, temp_dir, scan.settings['SPheno']['Input'])
        scan.spheno.run(scan.settings['SPheno']['Output'], temp_dir, log)
        if self.bad_point_check(scan, log):
            return
        if os.path.exists(scan.settings['SPheno']['Output']):
            log.info('SPheno spectrum produced')
            for run_now in scan.run_tools:
                try:
                    run_now.run(scan.settings['SPheno']['Output'], temp_dir, log)
                except Exception as e:
                    print(e)

            if scan.Short:
                spc = xslha.read(scan.settings['SPheno']['Output'])
                debug.command_line_log("echo " + ' '.join(map(str,point)) + ' ' + ' '.join(map(str,[spc.Value(obs['SLHA'][0], obs['SLHA'][1]) for obs in scan.observables.values()])) + " >> " + output_file, log)
            else:
                debug.command_line_log("cat " + scan.settings['SPheno']['Output']
                                   + " >> " + output_file, log)
                debug.command_line_log("echo \"ENDOFPARAMETERPOINT\" >> "
                                   + output_file, log)
                
            if scan.setup['Type'] in ["MLS", "MLS1", "MCMC", "MCMC_NN"]:
                log.info('Reading spectrum file')
                spc = xslha.read(scan.settings['SPheno']['Output'])
                try:
                    list_all.append(
                        [point, [spc.Value(obs['SLHA'][0], obs['SLHA'][1])
                                 for obs in scan.observables.values()]])
                    list_valid.append(point)
                    log.debug("Observables: %s"
                              % str([spc.Value(obs['SLHA'][0], obs['SLHA'][1])
                                    for obs in scan.observables.values()]))
                except:
#                    scan.invalid_points.put(point)
                    list_invalid.append(point)
                    log.warning('Observable(s) missing in SLHA file')
        else:
#            scan.invalid_points.put(point)
            list_invalid.append(point)
            
            # We keep the non-valid points for plotting
            if not scan.Short:
#                debug.command_line_log("echo " + ' '.join(map(str,point)) + " >> " + output_file, log)
#                
#            else:
                debug.command_line_log("cat " + scan.settings['SPheno']['Input']
                                   + " >> " + output_file, log)
                debug.command_line_log("echo \"ENDOFPARAMETERPOINT\" >> "
                                  + output_file, log)
            log.info('NO SPheno spectrum produced')