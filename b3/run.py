__author__ = 'ThorN'
__version__ = '1.8'

import argparse
import os
import sys
import traceback
from time import sleep

import b311
import b311.config
import b311.pkg_handler as pkg_handler
from b311 import HOMEDIR, B3_CONFIG_GENERATOR
from b311.functions import main_is_frozen, console_exit
from b311.update import DBUpdate

modulePath = pkg_handler.resource_directory(__name__)


def run_autorestart(args=None):
    """
    Run B3 in auto-restart mode.
    """
    restart_num = 0

    if main_is_frozen():
        # if we are running the frozen application we do not
        # need to run any script, just the executable itself
        script = ''
    else:
        # if we are running from sources, then sys.executable is set to `python`
        script = os.path.join(modulePath[:-3], 'b3_run.py')
        if not os.path.isfile(script):
            # must be running from the wheel, so there is no b3_run
            script = os.path.join('b3_run.py')
        if os.path.isfile(script + 'c'):
            script += 'c'

    if args:
        script = '%s %s %s --autorestart' % (sys.executable, script, ' '.join(args))
    else:
        script = '%s %s --autorestart' % (sys.executable, script)

    while True:

        try:

            try:
                import subprocess32 as subprocess
            except ImportError:
                import subprocess

            status = subprocess.run(script, shell=True)

            sys.stdout.write('Exited with status: %s ... ' % status)
            sys.stdout.flush()
            sleep(2)

            if status == 221:
                restart_num += 1
                sys.stdout.write('restart requested (%s)\n' % restart_num)
                sys.stdout.flush()
            elif status == 222:
                sys.stdout.write('shutdown requested!\n')
                sys.stdout.flush()
                break
            elif status == 220 or status == 223:
                sys.stdout.write('B3 error (check log file)\n')
                sys.stdout.flush()
                break
            elif status == 224:
                sys.stdout.write('B3 error (check console)\n')
                sys.stdout.flush()
                break
            elif status == 256:
                sys.stdout.write('python error, (check log file)\n')
                sys.stdout.flush()
                break
            elif status == 0:
                sys.stdout.write('normal shutdown\n')
                sys.stdout.flush()
                break
            elif status == 1:
                sys.stdout.write('general error (check console)\n')
                sys.stdout.flush()
                break
            else:
                restart_num += 1
                sys.stdout.write('unknown exit code (%s), restarting (%s)...\n' % (status, restart_num))
                sys.stdout.flush()

            sleep(4)

        except KeyboardInterrupt:
            print('Quit')
            break


def run_update(config=None):
    """
    Run the B3 update.
    param config: The B3 configuration file instance
    """
    update = DBUpdate(config)
    update.run()


def run_console(options):
    """
    Run B3 in console mode.
    :param options: command line options
    """
    analysis = None  # main config analysis result
    printexit = False  # whether the exit message has been printed alreadty or not

    try:

        if options.config:
            config = b311.getAbsolutePath(options.config, True)
            if not os.path.isfile(config):
                printexit = True
                console_exit('ERROR: configuration file not found (%s).\n'
                             'Please visit %s to create one.' % (config, B3_CONFIG_GENERATOR))
        else:
            config = None
            for p in ('b311.%s', 'conf/b311.%s', 'b311/conf/b311.%s',
                      os.path.join(HOMEDIR, 'b311.%s'), os.path.join(HOMEDIR, 'conf', 'b311.%s'),
                      os.path.join(HOMEDIR, 'b311', 'conf', 'b311.%s'), '@b311/conf/b311.%s'):
                for e in ('ini', 'cfg', 'xml'):
                    path = b311.getAbsolutePath(p % e, True)
                    if os.path.isfile(path):
                        print("Using configuration file: %s" % path)
                        config = path
                        sleep(3)
                        break

            if not config:
                printexit = True
                console_exit('ERROR: could not find any valid configuration file.\n'
                             'Please visit %s to create one.' % B3_CONFIG_GENERATOR)

        # LOADING MAIN CONFIGURATION
        main_config = b311.config.MainConfig(b311.config.load(config))
        analysis = main_config.analyze()
        if analysis:
            raise b311.config.ConfigFileNotValid('invalid configuration file specified')

        # START B3
        b311.start(main_config, options)

    except b311.config.ConfigFileNotValid:
        if analysis:
            print("CRITICAL: invalid configuration file specified:\n")
            for problem in analysis:
                print("  >>> %s\n" % problem)
        else:
            print("CRITICAL: invalid configuration file specified!")
        raise SystemExit(1)
    except SystemExit as msg:
        if not printexit and main_is_frozen():
            if sys.stdout != sys.__stdout__:
                sys.stdout = sys.__stdout__
                sys.stderr = sys.__stderr__
            print(msg)
            input("press any key to continue...")
        raise
    except:
        if sys.stdout != sys.__stdout__:
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__
        traceback.print_exc()
        input("press any key to continue...")


def main():
    """
    Main execution.
    """
    p = argparse.ArgumentParser()

    p.add_argument('-c', '--config', dest='config', default=None, metavar='b311.xml',help='B3 config file. Example: -c b311.ini')
    p.add_argument('-r', '--restart', action='store_true', dest='restart', default=False,help='Auto-restart B3 on crash')
    p.add_argument('-s', '--setup', action='store_true', dest='setup', default=False,help='Setup main b311.ini config file')
    p.add_argument('-u', '--update', action='store_true', dest='update', default=False,help='Update B3 database to latest version')
    p.add_argument('-v', '--version', action='version', default=False, version=b311.getB3versionString(),help='Show B3 version and exit')
    p.add_argument('-a', '--autorestart', action='store_true', dest='autorestart', default=False,help=argparse.SUPPRESS)

    (options, args) = p.parse_known_args()

    if not options.config and len(args) == 1:
        options.config = args[0]

    if options.setup:
        # setup procedure is deprecated: show configuration file generator web tool url instead
        sys.stdout.write('\n')
        console_exit("  *** NOTICE: the console setup procedure is deprecated!\n"
                     "  *** Please visit %s to generate a new B3 configuration file.\n" % B3_CONFIG_GENERATOR)

    if options.update:
        # UPDATE => CONSOLE
        run_update(config=options.config)

    if options.restart:
        # AUTORESTART => CONSOLE
        if options.config:
            run_autorestart(['--config', options.config] + args)
        else:
            run_autorestart([])

    else:
        run_console(options)


if __name__ == '__main__':
    main()
