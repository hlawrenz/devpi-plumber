import atexit
import contextlib
import os
import shutil
import subprocess

from devpi_plumber.client import DevpiClient
from six import iteritems
from twitter.common.contextutil import temporary_dir


@contextlib.contextmanager
def TestServer(users={}, indices={}, config={}, fail_on_output=['Traceback']):
    """
    Starts a devpi server to be used within tests.
    """
    with temporary_dir() as server_dir:

        server_options = {
            'port': 2414,
            'serverdir': server_dir}
        server_options.update(config)

        initialize_serverdir(server_options)

        with DevpiServer(server_options) as url:
            with DevpiClient(url, 'root', '') as client:

                for user, kwargs in iteritems(users):
                    client.create_user(user, **kwargs)

                for index, kwargs in iteritems(indices):
                    client.create_index(index, **kwargs)

                yield client

        _assert_no_logged_errors(fail_on_output, server_options['serverdir'] + '/.xproc/devpi-server/xprocess.log')


def import_state(serverdir, importdir):
    devpi_server_command(serverdir=serverdir, init=None)
    devpi_server_command(serverdir=serverdir, **{'import': importdir})


def export_state(serverdir, exportdir):
    devpi_server_command(serverdir=serverdir, export=exportdir)


def _assert_no_logged_errors(fail_on_output, logfile):
    with open(logfile) as f:
        logs = f.read()
    for message in fail_on_output:
        if message not in logs:
            continue
        if message == 'Traceback' and logs.count(message) == logs.count('ValueError: I/O operation on closed file'):
            # Heuristic to ignore false positives on the shutdown of replicas
            # The master might still be busy serving root/pypi/simple for a stopping replica
            continue
        raise RuntimeError(logs)


@contextlib.contextmanager
def DevpiServer(options):
    try:
        devpi_server_command(start=None, **options)
        yield 'http://localhost:{}'.format(options['port'])
    finally:
        devpi_server_command(stop=None, **options)


def devpi_server_command(**options):
    opts = ['--{}={}'.format(k, v) for k, v in iteritems(options) if v is not None]
    flags = ['--{}'.format(k) for k, v in iteritems(options) if v is None]
    subprocess.check_output(['devpi-server'] + opts + flags, stderr=subprocess.STDOUT)


serverdir_cache = '/tmp/devpi-plumber-cache'
atexit.register(shutil.rmtree, serverdir_cache, ignore_errors=True)


def initialize_serverdir(server_options):
    """
    Starting a new devpi-server is costly due to its initial sync with pypi.python.org.
    We can speedup this process by using the content of a cached serverdir.
    """
    def init_serverdir():
        devpi_server_command(init=None, **server_options)

    serverdir_new = server_options['serverdir']

    if os.path.exists(serverdir_new) and os.listdir(serverdir_new):
        # Don't touch already populated directory.
        return

    if 'no-root-pypi' in server_options:
        # Always run servers called with `--no-root-pypi in a freshly initialized serverdir.
        init_serverdir()
        return

    if 'master-url' in server_options:
        # Running as replica. Aways has to be a fresh sync.
        init_serverdir()
    else:
        # Running as master.
        if os.path.exists(serverdir_cache) and os.listdir(serverdir_cache):
            shutil.rmtree(serverdir_new)
            shutil.copytree(serverdir_cache, serverdir_new)
        else:
            init_serverdir()
            shutil.rmtree(serverdir_cache, ignore_errors=True)
            shutil.copytree(serverdir_new, serverdir_cache)
