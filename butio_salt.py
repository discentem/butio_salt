import salt.client
import salt.config
import salt.loader
import salt.output
import platform
import requests
import pprint
import sys
import json

##==================##
##======GlOBALS=====##
##==================##

## SALT LOADER

if platform.system == "Windows":
    minion_config_path = 'c:\\salt\\conf\\minion'
else:
    minion_config_path = '/etc/salt/minion'
__opts__ = salt.config.minion_config(minion_config_path)
__grains__ = salt.loader.grains(__opts__)
__opts__['grains'] = __grains__
__opts__['file_client'] = 'local'
__utils__ = salt.loader.utils(__opts__)
__salt__ = salt.loader.minion_mods(__opts__, utils=__utils__)
__serializers__ = salt.loader.serializers(__opts__)
__states__ = salt.loader.states(__opts__, __salt__, __utils__, __serializers__)
__states__.pack['__instance_id__'] = __grains__['id']
__states__.pack['__env__'] = 'base'
caller = salt.client.Caller(mopts=__opts__)

def output_state(state):
    salt.output.display_output(state, 'pprint_out', opts=__opts__)
    print('')


class GCEMetadataWrapper:
    '''Wrapper class for retrieving Instance & Project Metadata'''
    @staticmethod
    def return_request(request):
        '''Returns Get request if status code is 200; others returns None'''
        if request.status_code == 200:
            return request.content.decode('utf-8')
        return None

    def get_metadata_value(self, url):
        '''Executes Get request against GCP Metadata server with proper headers'''
        request = requests.get(url, headers={"Metadata-Flavor":"Google"})
        return self.return_request(request)

    def get_instance_metadata_value(self, key):
        '''Helper method for retrieving Instance Metadata values'''
        url = "http://metadata.google.internal/computeMetadata/v1/instance/{0}"
        url = url.format(key)
        return self.get_metadata_value(url)

    def get_project_metadata_value(self, key):
        '''Helper method for retrieving Project Metadata values'''
        url = "http://metadata.google.internal/computeMetadata/v1/project/{0}"
        url = url.format(key)
        return self.get_metadata_value(url)

def validate_and_parse_json(json_string, description=""):
    '''
    Checks if a string is valid json. If it is, it returns a dictionary
    of the data with json.loads().

    If it's not valid, this function makes a best effort to point the user
    to the mistake and exits.
    '''
    try:
        return json.loads(json_string)
    except json.decoder.JSONDecodeError as err:
        err_list = (err.doc).split('\n')
        RED = "\033[1;31m"
        RESET = "\033[0;0m"
        print("kickstart-salt has crashed while try to parse the json block labeled as: {0}. ".format(description), end='\n')
        print("We've tried to highlight a line which ", end='')
        print("is close to the error, though the highlighting may be ", end='')
        print("a few lines off." + '\n')
        print(">>> Error: ", end='')
        print(err)
        for line in err_list:
            if err_list.index(line) == int(err.lineno)-1:
                sys.stdout.write(RED)
                print(line)
                sys.stdout.write(RESET)
                continue

            print(line)
        exit(1)

##==================##
##==END OF GLOBALS==##
##==================##


class ButioSalt:
    @staticmethod
    def get_shell():
        return (
            __salt__['grains.filter_by'](
                {
                    'default': '/usr/bin/sh',
                    'Windows': 'powershell'

                },
                grain='os_family'
            )
        )

    def set_dns(dns_entries):
        dns_state = (
            __salt__['grains.filter_by'](
                {   'default': (
                        __states__['file.append'](
                            '/etc/resolv.conf',
                            text=dns_entries
                        )
                     ),
                     'Windows': (
                        __states__['network.managed'](
                            'Local Area Connection',
                            dns_proto='static',
                            dns_servers=dns_entries
                        )
                     )
                },
                grain="os_family"
            )
        )

        output_state(dns_state)


    @staticmethod
    def write_etc_salt_master_d(etc_salt_master_d):
        master_d_states = {}
        for conf_name, conf in etc_salt_master_d.items():
            conf_path = "/etc/salt/master.d/{0}".format(conf_name)
            master_d_states[conf_path] = (
                __states__['file.serialize'](
                    conf_path,
                    makedirs=True,
                    dataset=conf,
                    formatter='yaml'
                )
            )

        # if any of the master.d files change, restart salt-master
        restart_salt_master = False
        for id, state in master_d_states.items():
            output_state(state)
            # if we aren't already restarting, check if we should...
            if (restart_salt_master == False) and (state['changes']):
                restart_salt_master = True

        if restart_salt_master:
            output_state(__salt__['service.restart']('salt-master'))

    def __init__(self,
                 dns_entries,
                 etc_salt_master_d,
                 bootstrap_salt_save_path,
                 bootstrap_salt_hash_type,
                 bootstrap_salt_expected_hash):

        self.dns_entries = dns_entries
        self.etc_salt_master_d = etc_salt_master_d
        self.bootstrap_salt_save_path = bootstrap_salt_save_path
        self.bootstrap_salt_hash_type = bootstrap_salt_hash_type
        self.bootstrap_salt_expected_hash = bootstrap_salt_expected_hash

        self.shell = self.get_shell()


        ## Bootstrap functions
        self.set_dns(dns_entries=self.dns_entries)
        self.write_etc_salt_master_d(
            etc_salt_master_d=self.etc_salt_master_d
        )



class ButioSaltGoogleComputeEngine(ButioSalt):
    def generate_dns_entries(self):
        project_id = self.METADATA.get_project_metadata_value("project-id")

        dns_servers = [
            "search c.{0}.internal google.internal".format(project_id),
        ]

        for entry in self.butio_salt_args['dns_servers']:
            dns_servers.append('nameserver {0}'.format(entry))

        dns_servers.append("nameserver 169.254.169.254")

        return dns_servers

    def __init__(self):

        self.METADATA = GCEMetadataWrapper()
        self.butio_salt_args = validate_and_parse_json(
            self.METADATA.get_instance_metadata_value(
                'attributes/butio_salt_args'
            ),
            description="butio_salt_args"
        )

        self.dns_entries = self.generate_dns_entries()
        self.etc_salt_master_d = (
            self.butio_salt_args['/etc/salt/master.d/']
        )

        self.bootstrap_salt_save_path = (
            self.butio_salt_args['bootstrap_salt_save_path']
        )
        self.bootstrap_salt_hash_type = (
            self.butio_salt_args['bootstrap_salt_hash_type']
        )
        self.bootstrap_salt_expected_hash = (
            self.butio_salt_args['bootstrap_salt_expected_hash']
        )


        super().__init__(dns_entries=self.dns_entries,
                         etc_salt_master_d=self.etc_salt_master_d,
                         bootstrap_salt_save_path=self.bootstrap_salt_save_path,
                         bootstrap_salt_hash_type=self.bootstrap_salt_hash_type,
                         bootstrap_salt_expected_hash=(
                            self.bootstrap_salt_expected_hash
                         ))

ButioSaltGoogleComputeEngine()
