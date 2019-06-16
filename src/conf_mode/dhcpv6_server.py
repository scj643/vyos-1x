#!/usr/bin/env python3
#
# Copyright (C) 2018 VyOS maintainers and contributors
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 or later as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#

import sys
import os
import ipaddress

import jinja2

import vyos.validate

from vyos.config import Config
from vyos import ConfigError

config_file = r'/etc/dhcp/dhcpdv6.conf'
lease_file = r'/config/dhcpdv6.leases'
daemon_config_file = r'/etc/default/isc-dhcpv6-server'

# Please be careful if you edit the template.
config_tmpl = """
### Autogenerated by dhcpv6_server.py ###

# For options please consult the following website:
# https://www.isc.org/wp-content/uploads/2017/08/dhcp43options.html

log-facility local7;
{%- if preference %}
option dhcp6.preference {{ preference }};
{%- endif %}

# Shared network configration(s)
{% for network in shared_network %}
{%- if not network.disabled -%}
shared-network {{ network.name }} {
    {%- for subnet in network.subnet %}
    subnet6 {{ subnet.network }} {
        {%- for range in subnet.range6_prefix %}
        range6 {{ range.prefix }}{{ " temporary" if range.temporary }};
        {%- endfor %}
        {%- for range in subnet.range6 %}
        range6 {{ range.start }} {{ range.stop }};
        {%- endfor %}
        {%- if subnet.domain_search %}
        option dhcp6.domain-search {{ subnet.domain_search | join(', ') }};
        {%- endif %}
        {%- if subnet.lease_def %}
        default-lease-time {{ subnet.lease_def }};
        {%- endif %}
        {%- if subnet.lease_max %}
        max-lease-time {{ subnet.lease_max }};
        {%- endif %}
        {%- if subnet.lease_min %}
        min-lease-time {{ subnet.lease_min }};
        {%- endif %}
        {%- if subnet.dns_server %}
        option dhcp6.name-servers {{ subnet.dns_server | join(', ') }};
        {%- endif %}
        {%- if subnet.nis_domain %}
        option dhcp6.nis-domain-name "{{ subnet.nis_domain }}";
        {%- endif %}
        {%- if subnet.nis_server %}
        option dhcp6.nis-servers {{ subnet.nis_server | join(', ') }};
        {%- endif %}
        {%- if subnet.nisp_domain %}
        option dhcp6.nisp-domain-name "{{ subnet.nisp_domain }}";
        {%- endif %}
        {%- if subnet.nisp_server %}
        option dhcp6.nisp-servers {{ subnet.nisp_server | join(', ') }};
        {%- endif %}
        {%- if subnet.sip_address %}
        option dhcp6.sip-servers-addresses {{ subnet.sip_address | join(', ') }};
        {%- endif %}
        {%- if subnet.sip_hostname %}
        option dhcp6.sip-servers-names {{ subnet.sip_hostname | join(', ') }};
        {%- endif %}
        {%- if subnet.sntp_server %}
        option dhcp6.sntp-servers {{ subnet.sntp_server | join(', ') }};
        {%- endif %}
        {%- for host in subnet.static_mapping %}
        {% if not host.disabled -%}
        host {{ network.name }}_{{ host.name }} {
            host-identifier option dhcp6.client-id "{{ host.client_identifier }}";
            fixed-address6 {{ host.ipv6_address }};
        }
        {%- endif %}
        {%- endfor %}
    }
    {%- endfor %}
}
{%- endif %}
{% endfor %}

"""

daemon_tmpl = """
### Autogenerated by dhcp_server.py ###

# sourced by /etc/init.d/isc-dhcpv6-server

DHCPD_CONF=/etc/dhcp/dhcpdv6.conf
DHCPD_PID=/var/run/dhcpdv6.pid
OPTIONS="-6 -lf {{ lease_file }}"
INTERFACES=""
"""

default_config_data = {
    'lease_file': lease_file,
    'preference': '',
    'disabled': False,
    'shared_network': []
}

def get_config():
    dhcpv6 = default_config_data
    conf = Config()
    if not conf.exists('service dhcpv6-server'):
        return None
    else:
        conf.set_level('service dhcpv6-server')

    # Check for global disable of DHCPv6 service
    if conf.exists('disable'):
        dhcpv6['disabled'] = True
        return dhcpv6

    # Preference of this DHCPv6 server compared with others
    if conf.exists('preference'):
        dhcpv6['preference'] = conf.return_value('preference')

    # check for multiple, shared networks served with DHCPv6 addresses
    if conf.exists('shared-network-name'):
        for network in conf.list_nodes('shared-network-name'):
            conf.set_level('service dhcpv6-server shared-network-name {0}'.format(network))
            config = {
                'name': network,
                'disabled': False,
                'subnet': []
            }

            # If disabled, the shared-network configuration becomes inactive
            if conf.exists('disable'):
                config['disabled'] = True

            # check for multiple subnet configurations in a shared network
            if conf.exists('subnet'):
                for net in conf.list_nodes('subnet'):
                    conf.set_level('service dhcpv6-server shared-network-name {0} subnet {1}'.format(network, net))
                    subnet = {
                        'network': net,
                        'range6_prefix': [],
                        'range6': [],
                        'default_router': '',
                        'dns_server': [],
                        'domain_name': '',
                        'domain_search': [],
                        'lease_def': '',
                        'lease_min': '',
                        'lease_max': '',
                        'nis_domain': '',
                        'nis_server': [],
                        'nisp_domain': '',
                        'nisp_server': [],
                        'sip_address': [],
                        'sip_hostname': [],
                        'sntp_server': [],
                        'static_mapping': []
                    }

                    # For any subnet on which addresses will be assigned dynamically, there must be at
                    # least one address range statement. The range statement gives the lowest and highest
                    # IP addresses in a range. All IP addresses in the range should be in the subnet in
                    # which the range statement is declared.
                    if conf.exists('address-range prefix'):
                        for prefix in conf.list_nodes('address-range prefix'):
                            range = {
                                'prefix': prefix,
                                'temporary': False
                            }

                            # Address range will be used for temporary addresses
                            if conf.exists('address-range prefix {0} temporary'.format(range['prefix'])):
                                range['temporary'] = True

                            # Append to subnet temporary range6 list
                            subnet['range6_prefix'].append(range)

                    if conf.exists('address-range start'):
                        for range in conf.list_nodes('address-range start'):
                            range = {
                                'start': range,
                                'stop': conf.return_value('address-range start {0} stop'.format(range))
                            }

                            # Append to subnet range6 list
                            subnet['range6'].append(range)

                    # The domain-search option specifies a 'search list' of Domain Names to be used
                    # by the client to locate not-fully-qualified domain names.
                    if conf.exists('domain-search'):
                        for domain in conf.return_values('domain-search'):
                            subnet['domain_search'].append('"' + domain + '"')

                    # IPv6 address valid lifetime
                    #  (at the end the address is no longer usable by the client)
                    #  (set to 30 days, the usual IPv6 default)
                    if conf.exists('lease-time default'):
                        subnet['lease_def'] = conf.return_value('lease-time default')

                    # Time should be the maximum length in seconds that will be assigned to a lease.
                    # The only exception to this is that Dynamic BOOTP lease lengths, which are not
                    # specified by the client, are not limited by this maximum.
                    if conf.exists('lease-time maximum'):
                        subnet['lease_max'] = conf.return_value('lease-time maximum')

                    # Time should be the minimum length in seconds that will be assigned to a lease
                    if conf.exists('lease-time minimum'):
                        subnet['lease_min'] = conf.return_value('lease-time minimum')

                    # Specifies a list of Domain Name System name servers available to the client.
                    # Servers should be listed in order of preference.
                    if conf.exists('name-server'):
                        subnet['dns_server'] = conf.return_values('name-server')

                    # Ancient NIS (Network Information Service) domain name
                    if conf.exists('nis-domain'):
                        subnet['nis_domain'] = conf.return_value('nis-domain')

                    # Ancient NIS (Network Information Service) servers
                    if conf.exists('nis-server'):
                        subnet['nis_server'] = conf.return_values('nis-server')

                    # Ancient NIS+ (Network Information Service) domain name
                    if conf.exists('nisplus-domain'):
                        subnet['nisp_domain'] = conf.return_value('nisplus-domain')

                    # Ancient NIS+ (Network Information Service) servers
                    if conf.exists('nisplus-server'):
                        subnet['nisp_server'] = conf.return_values('nisplus-server')

                    # Prefix Delegation (RFC 3633)
                    if conf.exists('prefix-delegation'):
                        print('TODO: This option is actually not implemented right now!')

                    # Local SIP server that is to be used for all outbound SIP requests - IPv6 address
                    if conf.exists('sip-server-address'):
                        subnet['sip_address'] = conf.return_values('sip-server-address')

                    # Local SIP server that is to be used for all outbound SIP requests - hostname
                    if conf.exists('sip-server-name'):
                        for hostname in conf.return_values('sip-server-name'):
                            subnet['sip_hostname'].append('"' + hostname + '"')

                    # List of local SNTP servers available for the client to synchronize their clocks
                    if conf.exists('sntp-server'):
                        subnet['sntp_server'] = conf.return_values('sntp-server')

                    #
                    # Static DHCP v6 leases
                    #
                    if conf.exists('static-mapping'):
                        for mapping in conf.list_nodes('static-mapping'):
                            conf.set_level('service dhcpv6-server shared-network-name {0} subnet {1} static-mapping {2}'.format(network, net, mapping))
                            mapping = {
                               'name': mapping,
                               'disabled': False,
                               'ipv6_address': '',
                               'client_identifier': '',
                            }

                            # This static lease is disabled
                            if conf.exists('disable'):
                                mapping['disabled'] = True

                            # IPv6 address used for this DHCP client
                            if conf.exists('ipv6-address'):
                                mapping['ipv6_address'] = conf.return_value('ipv6-address')

                            # This option specifies the client’s DUID identifier. DUIDs are similar but different from DHCPv4 client identifiers
                            if conf.exists('identifier'):
                                mapping['client_identifier'] = conf.return_value('identifier')

                            # append static mapping configuration tu subnet list
                            subnet['static_mapping'].append(mapping)

                    # append subnet configuration to shared network subnet list
                    config['subnet'].append(subnet)


            # append shared network configuration to config dictionary
            dhcpv6['shared_network'].append(config)

    return dhcpv6

def verify(dhcpv6):
    if dhcpv6 is None:
        return None

    if dhcpv6['disabled']:
        return None

    # If DHCP is enabled we need one share-network
    if len(dhcpv6['shared_network']) == 0:
        raise ConfigError('No DHCPv6 shared networks configured.\n' \
                          'At least one DHCPv6 shared network must be configured.')

    # Inspect shared-network/subnet
    subnets = []
    listen_ok = False

    for network in dhcpv6['shared_network']:
        # A shared-network requires a subnet definition
        if len(network['subnet']) == 0:
            raise ConfigError('No DHCPv6 lease subnets configured for {0}. At least one\n' \
                              'lease subnet must be configured for each shared network.'.format(network['name']))

        range6_start = []
        range6_stop = []
        for subnet in network['subnet']:
            # Ususal range declaration with a start and stop address
            for range6 in subnet['range6']:
                # shorten names
                start = range6['start']
                stop = range6['stop']

                # DHCPv6 stop address is required
                if start and not stop:
                    raise ConfigError('DHCPv6 range stop address for start {0} is not defined!'.format(start))

                # Start address must be inside network
                if not ipaddress.ip_address(start) in ipaddress.ip_network(subnet['network']):
                    raise ConfigError('DHCPv6 range start address {0} is not in subnet {1}\n' \
                                      'specified for shared network {2}!'.format(start, subnet['network'], network['name']))

                # Stop address must be inside network
                if not ipaddress.ip_address(stop) in ipaddress.ip_network(subnet['network']):
                     raise ConfigError('DHCPv6 range stop address {0} is not in subnet {1}\n' \
                                       'specified for shared network {2}!'.format(stop, subnet['network'], network['name']))

                # Stop address must be greater or equal to start address
                if not ipaddress.ip_address(stop) >= ipaddress.ip_address(start):
                    raise ConfigError('DHCPv6 range stop address {0} must be greater or equal\n' \
                                      'to the range start address {1}!'.format(stop, start))

                # DHCPv6 range start address must be unique - two ranges can't
                # start with the same address - makes no sense
                if start in range6_start:
                    raise ConfigError('Conflicting DHCPv6 lease range:\n' \
                                      'Pool start address {0} defined multipe times!'.format(start))
                else:
                    range6_start.append(start)

                # DHCPv6 range stop address must be unique - two ranges can't
                # end with the same address - makes no sense
                if stop in range6_stop:
                    raise ConfigError('Conflicting DHCPv6 lease range:\n' \
                                      'Pool stop address {0} defined multipe times!'.format(stop))
                else:
                    range6_stop.append(stop)

            # We also have prefixes that require checking
            for prefix in subnet['range6_prefix']:
                # If configured prefix does not match our subnet, we have to check that it's inside
                if ipaddress.ip_network(prefix['prefix']) != ipaddress.ip_network(subnet['network']):
                    # Configured prefixes must be inside our network
                    if not ipaddress.ip_network(prefix['prefix']) in ipaddress.ip_network(subnet['network']):
                        raise ConfigError('DHCPv6 prefix {0} is not in subnet {1}\n' \
                                          'specified for shared network {2}!'.format(prefix['prefix'], subnet['network'], network['name']))

        # DHCPv6 requires at least one configured address range or one static mapping
        if not network['disabled']:
            if vyos.validate.is_subnet_connected(subnet['network']):
                listen_ok = True

        # DHCPv6 subnet must not overlap. ISC DHCP also complains about overlapping
        # subnets: "Warning: subnet 2001:db8::/32 overlaps subnet 2001:db8:1::/32"
        net = ipaddress.ip_network(subnet['network'])
        for n in subnets:
            net2 = ipaddress.ip_network(n)
            if (net != net2):
                if net.overlaps(net2):
                    raise ConfigError('DHCPv6 conflicting subnet ranges: {0} overlaps {1}'.format(net, net2))

    if not listen_ok:
        raise ConfigError('None of the DHCPv6 subnets are connected to a subnet6 on\n' \
                          'this machine. At least one subnet6 must be connected such that\n' \
                          'DHCPv6 listens on an interface!')


    return None

def generate(dhcpv6):
    if dhcpv6 is None:
        return None

    if dhcpv6['disabled']:
        print('Warning: DHCPv6 server will be deactivated because it is disabled')
        return None

    tmpl = jinja2.Template(config_tmpl)
    config_text = tmpl.render(dhcpv6)
    with open(config_file, 'w') as f:
        f.write(config_text)

    tmpl = jinja2.Template(daemon_tmpl)
    config_text = tmpl.render(dhcpv6)
    with open(daemon_config_file, 'w') as f:
        f.write(config_text)

    return None

def apply(dhcpv6):
    if (dhcpv6 is None) or dhcpv6['disabled']:
        # DHCP server is removed in the commit
        os.system('sudo systemctl stop isc-dhcpv6-server.service')
        if os.path.exists(config_file):
            os.unlink(config_file)
        if os.path.exists(daemon_config_file):
            os.unlink(daemon_config_file)
    else:
        # If our file holding DHCPv6 leases does yet not exist - create it
        if not os.path.exists(lease_file):
            os.mknod(lease_file)

        os.system('sudo systemctl restart isc-dhcpv6-server.service')

    return None

if __name__ == '__main__':
    try:
        c = get_config()
        verify(c)
        generate(c)
        apply(c)
    except ConfigError as e:
        print(e)
        sys.exit(1)
