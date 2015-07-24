# Copyright 2015 Janos Czentye <czentye@tmit.bme.hu>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at:
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Wrapper module for handling emulated test topology based on Mininet.
"""

from mininet import clean
from mininet.net import VERSION as MNVERSION
from mininet.net import Mininet, MininetWithControlNet
from mininet.node import RemoteController, RemoteSwitch
from mininet.topo import Topo
from escape.infr import log
from escape.util.nffg import NFFG
from escape import CONFIG


class AbstractTopology(Topo):
  """
  Abstract class for representing emulated topology.

  Have the functions to build a ESCAPE-specific topology.

  Can be used to define reusable topology similar to Mininet's high-level API.
  Reusable, convenient and pre-defined way to define a topology, but less
  flexible and powerful.
  """
  # Default host options
  default_host_opts = None
  # Default switch options
  default_switch_opts = None
  # Default link options
  default_link_opts = None
  # Default EE options
  default_EE_opts = None

  def __init__ (self, hopts=None, sopts=None, lopts=None, eopts=None):
    super(AbstractTopology, self).__init__(hopts, sopts, lopts, eopts)
    self.construct()

  def construct (self):
    raise NotImplementedError("Not implemented yet!")


class FallbackStaticTopology(AbstractTopology):
  """
  Topology class for testing purposes and serve as a fallback topology.

  Use the static way for topology compilation.
  """

  def construct (self):
    h1 = self.addHost('H1')
    h2 = self.addHost('H2')
    s1 = self.addSwitch('S1')
    self.addLink(s1, h1)
    self.addLink(s1, h2)


class FallbackDynamicTopology(AbstractTopology):
  """
  Topology class for testing purposes and serve as a fallback topology.

  Use the dynamic way for topology compilation.
  """

  def construct (self):
    # TODO - implement
    pass


class InternalControllerProxy(RemoteController):
  """
  Controller class for emulated Mininet network. Making connection with
  internal controller initiated by POXDomainAdapter.
  """

  def __init__ (self, name="InternalPOXController", ip='127.0.0.1', port=6653,
       **kwargs):
    """
    Init.

    :param name: name of the controller (default: InternalPOXController)
    :type name: str
    :param ip: IP address (default: 127.0.0.1)
    :type ip: str
    :param port: port number (default 6633)
    :type port: int
    """
    super(InternalControllerProxy, self).__init__(name, ip, port, **kwargs)

  def checkListening (self):
    """
    Check the controller port is open.
    """
    listening = self.cmd("echo A | telnet -e A %s %d" % (self.ip, self.port))
    if 'Connected' not in listening:
      log.debug(
        "Unable to contact with internal controller at %s:%d. Waiting..." % (
          self.ip, self.port))


class ESCAPENetworkBridge(object):
  """
  Internal class for representing the emulated topology.

  Represents a container class for network elements such as switches, nodes,
  execution environments, links etc. Contains network management functions
  similar to Mininet's mid-level API extended with ESCAPEv2 related capabilities

  Separate the interface using internally from original Mininet object to
  implement loose coupling and avoid changes caused by Mininet API changes
  e.g. 2.1.0 -> 2.2.0

  Follows Bridge design pattern.
  """

  def __init__ (self, network=None):
    """
    Initialize Mininet implementation with proper attributes.
    Use network as the hided Mininet topology if it's given.

    :param network: use this specific Mininet object for init (default: None)
    :type network: :class:`mininet.net.MininetWithControlNet`
    :return: None
    """
    log.debug("Init emulated topology based on Mininet v%s" % MNVERSION)
    if network is not None:
      self.__mininet = network
    else:
      log.warning(
        "Network implementation object is missing! Use Builder class instead "
        "of direct initialization. Creating bare Mininet object anyway...")
      self.__mininet = Mininet(controller=InternalControllerProxy)
    # Need to clean after shutdown
    self._need_clean = None
    # There is no such flag in the Mininet class so using this
    self.started = False

  @property
  def network (self):
    """
    Internal network representation.

    :return: network representation
    :rtype: :class:`mininet.net.MininetWithControlNet`
    """
    return self.__mininet

  def get_topology (self):
    """
    Return with the topology.

    :return:
    """
    return True

  def start_network (self):
    """
    Start network.
    """
    log.debug("Starting Mininet network...")
    if self.__mininet is not None:
      self.__mininet.start()
      log.debug("Mininet network has been started!")
      self.started = True
    else:
      log.error("Missing topology! Skipping emulation...")

  def stop_network (self):
    """
    Stop network.
    """
    log.debug("Shutting down Mininet network...")
    if self.__mininet is not None:
      if self.started:
        self.__mininet.stop()
        log.debug("Mininet network has been stopped!")
        self.started = False
      else:
        log.warning("Mininet network is not started yet! Skipping stop task...")
    if self._need_clean:
      self.cleanup()

  def cleanup (self):
    """
    Clean up junk which might be left over from old runs.

    ..seealso::
      :func:`mininet.clean.cleanup() <mininet.clean.cleanup>`
    """
    if self.started:
      log.warning(
        "Mininet network is not stopped yet! Skipping cleanup task...")
    else:
      log.info("Cleanup after Mininet emulation...")
      clean.cleanup()


class TopologyBuilderException(Exception):
  """
  Exception class for topology errors.
  """
  pass


class ESCAPENetworkBuilder(object):
  """
  Builder class for topology.

  Update the network object based on the parameters if it's given or create
  an empty instance.

  Always return with an ESCAPENetworkBridge instance which offer a generic
  interface for created :any::`Mininet` object and hide implementation's nature.

  Follows Builder design pattern.
  """
  # Default initial options for Mininet
  default_opts = {"controller": InternalControllerProxy,  # Use own Controller
                  'build': False,  # Not build during init
                  'inNamespace': False,  # Not start element in namespace
                  'autoSetMacs': True,  # Set simple MACs
                  'autoStaticArp': True,  # Set static ARP entries
                  'listenPort': None}

  def __init__ (self, net=None, opts=None, fallback=True, run_dry=True):
    """
    Initialize NetworkBuilder.

    If the topology definition is not found, an exception will be raised or
    an empty :any::`Mininet` topology will be created if ``run_dry`` is set.

    :param net: update given Mininet object instead of creating a new one
    :type net: :any::`Mininet`
    :param opts: update default options with the given opts
    :type opts: dict
    :param fallback: search for fallback topology (default: True)
    :type fallback: bool
    :param run_dry: do not raise an Exception and return with bare Mininet obj.
    :type run_dry: bool
    :return: None
    """
    self.opts = dict(self.default_opts)
    if opts is not None:
      self.opts.update(opts)
      self.fallback = fallback
    self.run_dry = run_dry
    if net is not None:
      if isinstance(net, Mininet):
        # Initial settings - Create new Mininet object if necessary
        self.mn = net
      else:
        raise RuntimeError(
          "Network object's type must be a derived class of Mininet!")
    else:
      # self.mn = Mininet(**self.opts)
      self.mn = MininetWithControlNet(**self.opts)

  def __init_from_NFFG (self, nffg):
    """
    Initialize topology from :any:`NFFG`.

    :param nffg: topology
    :type nffg: :any:`NFFG`
    :return: None
    """
    # TODO -implement
    raise NotImplementedError()

  def __init_from_AbstractTopology (self, topo_class):
    """
    Build topology from pre-defined Topology class.

    :param topo_class: topology
    :type topo_class: :any:`AbstractTopology`
    :return: None
    """
    self.mn.topo = topo_class()
    self.mn.build()

  def __init_from_CONFIG (self, path=None):
    """
    Build a pre-defined topology from an NFFG stored in a file.
    The file path is searched in CONFIG with tha name ``TOPO``.

    :param path: additional file path
    :type path: str
    :return: None
    """
    if path is None:
      path = CONFIG.get_mininet_topology()
    if path is None:
      log.warning("Topology is missing from CONFIG!")
      raise TopologyBuilderException("Missing Topology!")
    else:
      try:
        with open(path, 'r') as f:
          self.__init_from_NFFG(NFFG.parse(f.read()))
      except IOError:
        log.debug("Additional topology file not found: %s" % path)
        raise TopologyBuilderException("Missing topology file!")
      except ValueError as e:
        log.error(
          "An error occurred when load topology from file: %s" % e.message)
        raise TopologyBuilderException("File parsing error!")

  def get_network (self):
    """
    Return the bridge to the built network.

    :return: object representing the emulated network
    :rtype: :any:`ESCAPENetworkBridge`
    """
    # Create the Interface object
    network = ESCAPENetworkBridge(network=self.mn)
    # Additional settings
    network._need_clean = CONFIG.get_clean_after_shutdown()
    return network

  def build (self, topology=None):
    """
    Initialize network.

    1. If the additional ``topology`` is given then using that for init.
    2. If TOPO is not given, search topology description in CONFIG with the \
    name 'TOPO'.
    3. If TOPO not found or an Exception was raised, search for the fallback \
    topo with the name ``FALLBACK-TOPO``.
    4. If FALLBACK-TOPO not found raise an exception or run a bare Mininet \
    object if the run_dry attribute is set


    :param topology: optional topology representation
    :type topology: :any:`NFFG` or :any:`dict` or :any:`AbstractTopology`
    :return: object representing the emulated network
    :rtype: :any:`ESCAPENetworkBridge`
    """
    # Load topology
    try:
      if topology is None:
        log.info("Load Topology description from CONFIG...")
        self.__init_from_CONFIG()
      elif isinstance(topology, NFFG):
        self.__init_from_NFFG(nffg=topology)
      elif isinstance(topology, AbstractTopology):
        self.__init_from_AbstractTopology(topo=topology)
      else:
        raise RuntimeError("Unsupported topology format: %s" % type(topology))
      return self.get_network()
    except TopologyBuilderException:
      fallback = CONFIG.get_fallback_topology()
      if fallback and self.fallback:
        log.info("Load topo from fallback topology description...")
        self.__init_from_AbstractTopology(fallback)
      elif not self.run_dry:
        raise
        # SB: replace this part to get_network function
        # # Create the Interface object
        # network = ESCAPENetworkBridge(network=self.mn)
        # # Additional settings
        # network._need_clean = CONFIG.get_clean_after_shutdown()
        # return network
      return self.get_network()

  def create_ee (self, name, **params):
    """
    Create and add a new EE to mininet network.

    The type of EE can be local NETCONF-based, remote NETCONF-based or static.
    """
    ee_type = params['ee_type']
    if ee_type == 'netconf':
      # create local NETCONF-based EE
      sw = self.mn.addSwitch(name)
      agt = self.mn.addAgent('agt_' + name)
      agt.setSwitch(sw)
      return agt, sw
    elif ee_type == 'remote':
      # create remote NETCONF-based EE
      # NOT tested yet
      p = copy.deepcopy(params)
      p['cls'] = None
      p['inNamespace'] = False
      p['dpid'] = p['remote_dpid']
      p['username'] = p['netconf_username']
      p['passwd'] = p['netconf_passwd']
      p['conf_ip'] = p['remote_conf_ip']
      p['agentPort'] = p['remote_netconf_port']
      sw = self.mn.addRemoteSwitch(name, **p)
      agt = self.mn.addAgent('agt_' + name, **p)
      agt.setSwitch(sw)
      return agt, sw
    else:
      pass
      # # TODO: make it backward compatible
      # # create static EE
      # h = self.net.addEE(**params)
      # if 'cores' in ee:
      #   h.setCPUs(**ee['cores'])
      # if 'frac' in ee:
      #   h.setCPUFrac(**ee['frac'])
      # if 'vlanif' in ee:
      #   for vif in ee['vlaninf']:
      #     # TODO: In miniedit it was after self.net.build()
      #     h.cmdPrint('vconfig add '+name+'-eth0 '+vif[1])
      #     h.cmdPrint('ifconfig '+name+'-eth0.'+vif[1]+' '+vif[0])

  def create_switch (self, name, **params):
    """
    Create and add a new OF switch intance to mininet network.
    """
    sw = self.mn.addSwitch(name, **params)
    if 'openflowver' in params:
      sw.setOpenFlowVersion(params['openflowver'])
    if 'ip' in params:
      sw.setSwitchIP(params['ip'])
    return sw

  def create_controller (self, name='c0', **params):
    """
    Create and add a new OF controller to mininet network.

    default controller: InternalControllerProxy
    """
    return self.mn.addController(name, **params)

  def create_sap (self, name, **params):
    """
    Create and add a new SAP to mininet network.
    """
    return self.mn.addHost(name, **params)

  def create_link (self, node1, node2, port1=None, port2=None, **params):
    """
    Create a link between node1 and node2.
    """

    def is_remote (node):
      return isinstance(node, RemoteSwitch)

    def is_local (node):
      return not is_remote(node)

    remote = filter(is_remote, [node1, node2])
    local = filter(is_local, [node1, node2])
    if not remote:
      self.mn.addLink(node1, node2, port1, port2, **params)
    else:
      sw = local[0]
      r = remote[0]
      intfName = r.params['local_intf_name']
      r_mac = None  # unknown, r.params['remote_mac']
      r_port = r.params['remote_port']
      # self._debug('\tadd hw interface (%s) to node (%s)' % (intfName,
      # sw.name))

      # This hack avoids calling __init__ which always makeIntfPair()
      link = Link.__new__(Link)
      i1 = Intf(intfName, node=sw, link=link)
      i2 = Intf(intfName, node=r, mac=r_mac, port=r_port, link=link)
      i2.mac = r_mac  # mn runs 'ifconfig', which resets mac to None
      #
      link.intf1, link.intf2 = i1, i2
