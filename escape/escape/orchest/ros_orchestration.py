# Copyright 2017 Janos Czentye
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
Contains classes relevant to Resource Orchestration Sublayer functionality.
"""
import ast
from collections import OrderedDict

from escape.adapt.virtualization import VirtualizerManager
from escape.orchest import log as log, LAYER_NAME
from escape.orchest.ros_mapping import ResourceOrchestrationMapper
from escape.util.config import CONFIG
from escape.util.mapping import AbstractOrchestrator, ProcessorError
from escape.util.misc import VERBOSE
from escape.util.virtualizer_helper import detect_bb_nf_from_path, \
  NF_PATH_TEMPLATE


class ResourceOrchestrator(AbstractOrchestrator):
  """
  Main class for the handling of the ROS-level mapping functions.
  """
  # Default Mapper class as a fallback mapper
  DEFAULT_MAPPER = ResourceOrchestrationMapper
  """Default Mapper class as a fallback mapper"""

  def __init__ (self, layer_API):
    """
    Initialize main Resource Orchestration Layer components.

    :param layer_API: layer API instance
    :type layer_API: :any:`ResourceOrchestrationAPI`
    :return: None
    """
    super(ResourceOrchestrator, self).__init__(layer_API=layer_API)
    log.debug("Init %s" % self.__class__.__name__)
    self.nffgManager = NFFGManager()
    # Init virtualizer manager
    # Listeners must be weak references in order the layer API can garbage
    # collected
    self.virtualizerManager = VirtualizerManager()
    self.virtualizerManager.addListeners(layer_API, weak=True)
    if CONFIG.get_nfib_enabled():
      # Init NFIB manager
      from escape.orchest.nfib_mgmt import NFIBManager
      self.nfibManager = NFIBManager().initialize()
    else:
      log.debug("NFIB component is disabled!")
      self.nfibManager = None

  def finalize (self):
    """
    Finalize func for class.

    :return: None
    """
    if self.nfibManager:
      self.nfibManager.finalize()

  def instantiate_nffg (self, nffg, continued_request_id=None):
    """
    Main API function for NF-FG instantiation.

    :param nffg: NFFG instance
    :type nffg: :class:`NFFG`
    :param continued_request_id: use explicit request id if request is
      continued after a trial and error (default: False)
    :type continued_request_id: str or None
    :return: mapped NFFG instance
    :rtype: :class:`NFFG`
    """
    log.debug("Invoke %s to instantiate given NF-FG" % self.__class__.__name__)
    if not continued_request_id:
      # Store newly created NF-FG
      self.nffgManager.save(nffg)
    else:
      # Use the original NFFG requested for getting the original request
      nffg = self.nffgManager.get(nffg_id=continued_request_id)
      log.info("Using original request for remapping: %s" % nffg)
    # Get Domain Virtualizer to acquire global domain view
    global_view = self.virtualizerManager.dov
    # Notify remote visualizer about resource view of this layer if it's needed
    # notify_remote_visualizer(data=global_view.get_resource_info(),
    #                          id=LAYER_NAME)
    # Log verbose mapping request
    log.log(VERBOSE, "Orchestration Layer request graph:\n%s" % nffg.dump())
    # Start Orchestrator layer mapping
    if global_view is not None:
      # If the request is a bare NFFG, it is probably an empty topo for domain
      # deletion --> skip mapping to avoid BadInputException and forward
      # topo to adaptation layer
      if not continued_request_id:
        if nffg.is_bare():
          log.warning("No valid service request (VNFs/Flowrules/SGhops) has "
                      "been detected in SG request! Skip orchestration in "
                      "layer: %s and proceed with the bare %s..." %
                      (LAYER_NAME, nffg))
          if nffg.is_virtualized():
            if nffg.is_SBB():
              log.debug("Request is a bare SingleBiSBiS representation!")
            else:
              log.warning(
                "Detected virtualized representation with multiple BiSBiS "
                "nodes! Currently this type of virtualization is nut fully "
                "supported!")
          else:
            log.debug("Detected full view representation!")
          # Return with the original request
          return nffg
        else:
          log.info("Request check: detected valid NFFG content!")
      try:
        # Run NF-FG mapping orchestration
        mapped_nffg = self.mapper.orchestrate(input_graph=nffg,
                                              resource_view=global_view,
                                              continued=bool(
                                                continued_request_id))
        log.debug("NF-FG instantiation is finished by %s" %
                  self.__class__.__name__)
        return mapped_nffg
      except ProcessorError as e:
        log.warning("Mapping pre/post processing was unsuccessful! "
                    "Cause: %s" % e)
        # Propagate the ProcessError to API layer
        raise
    else:
      log.warning("Global view is not acquired correctly!")
    log.error("Abort orchestration process!")

  def collect_mapping_info (self, service_id):
    """
    Return with collected information of mapping of a given service.

    :param service_id: service request ID
    :type service_id: str
    :return: mapping info
    :rtype: dict
    """
    # Get the service NFFG based on service ID
    request = self.nffgManager.get(service_id)
    if request is None:
      log.error("Service request(id: %s) is not found!" % service_id)
      return "Service request is not found!"
    # Get the overall view a.k.a. DoV
    dov = self.virtualizerManager.dov.get_resource_info()
    # Collect NFs
    nfs = [nf.id for nf in request.nfs]
    log.debug("Collected NFs: %s" % nfs)
    return self.__collect_binding(dov=dov, nfs=nfs)

  @staticmethod
  def __collect_binding (dov, nfs):
    """
    Collect mapping of given NFs on the global view(DoV).

    :param dov: global topology
    :type dov: :class:`NFFG`
    :param nfs: list of NFs
    :type nfs: list
    :return: mapping
    :rtype: list of dict
    """
    mappings = []
    # Process NFs
    for nf_id in nfs:
      mapping = {}
      # Get the connected infra node
      if nf_id not in dov:
        log.warning("NF: %s is not found in the global topology(DoV)!" % nf_id)
        continue
      bisbis = [n.id for n in dov.infra_neighbors(nf_id)]
      log.log(VERBOSE, "Detected mapped BiSBiS node:" % bisbis)
      if len(bisbis) != 1:
        log.warning(
          "Detected unexpected number of BiSBiS node: %s!" % bisbis)
        continue
      bisbis = bisbis.pop()
      # Add NF id
      nf = {"id": nf_id, "ports": []}
      for dyn_link in dov.network[nf_id][bisbis].itervalues():
        port = OrderedDict(id=dyn_link.src.id)
        if dyn_link.src.l4 is not None:
          try:
            port['management'] = ast.literal_eval(dyn_link.src.l4)
          except SyntaxError:
            log.warning("L4 address entry: %s is not valid Python expression! "
                        "Add the original string..." % dyn_link.src.l4)
            port['management'] = dyn_link.src.l4
        nf['ports'].append(port)
      mapping['nf'] = nf
      # Add infra node ID and domain name
      bisbis = bisbis.split('@')
      bb_mapping = {"id": bisbis[0],
                    "domain": bisbis[1] if len(bisbis) > 1 else None}
      mapping['bisbis'] = bb_mapping
      mappings.append(mapping)
    return mappings

  def collect_mappings (self, mappings, slor_topo):
    """
    Collect mapping information of NF in given mappings and return with an
    extended mapping structure.

    :param mappings: received mapping object
    :type mappings: :class:`Virtualizer`
    :param slor_topo: layer view of topology
    :type slor_topo: :class:`NFFG`
    :return: mapping structure extended with embedding info
    :rtype: :class:`Virtualizer`
    """
    dov = self.virtualizerManager.dov.get_resource_info()
    response = mappings.yang_copy()
    log.debug("Start checking mappings...")
    for mapping in response:
      bb, nf = detect_bb_nf_from_path(path=mapping.object.get_value(),
                                      topo=slor_topo)
      if not nf:
        mapping.target.object.set_value("NOT_FOUND")
        mapping.target.domain.set_value("N/A")
        continue
      m_result = self.__collect_binding(dov=dov, nfs=[nf])
      if not m_result:
        log.warning("Mapping is not found for NF: %s!" % nf)
        mapping.target.object.set_value("NOT_FOUND")
        mapping.target.domain.set_value("N/A")
        continue
      try:
        node = m_result[0]['bisbis']['id']
      except KeyError:
        log.warning("Missing mapping node element from: %s" % m_result)
        node = "NOT_FOUND"
      try:
        domain = m_result[0]['bisbis']['domain']
      except KeyError:
        log.warning("Missing mapping domain element from: %s" % m_result)
        domain = "N/A"
      log.debug("Found mapping: %s@%s (domain: %s)" % (nf, node, domain))
      mapping.target.object.set_value(NF_PATH_TEMPLATE % (node, nf))
      mapping.target.domain.set_value(domain)
    return response

  @staticmethod
  def filter_info_request (info, slor_topo):
    """
    Filter out non-existent NFs from original request.

    :param info: parsed info object
    :type info: :class:`Info`
    :param slor_topo: layer view of topology
    :type slor_topo: :class:`NFFG`
    :return: original and modified Info object
    :rtype: :class:`Info`
    """
    log.debug("Filter info request based on layer view: %s..." % slor_topo.id)
    info = info.yang_copy()
    for attr in (getattr(info, e) for e in info._sorted_children):
      deletable = []
      for element in attr:
        if hasattr(element, "object"):
          bb, nf = detect_bb_nf_from_path(element.object.get_value(),
                                          slor_topo)
          if not nf:
            log.debug("Remove element: %s from request..." % element._tag)
            deletable.append(element)
      for d in deletable:
        attr.remove(d)
    return info


class NFFGManager(object):
  """
  Store, handle and organize Network Function Forwarding Graphs.
  """

  def __init__ (self):
    """
    Init.

    :return: None
    """
    super(NFFGManager, self).__init__()
    log.debug("Init %s" % self.__class__.__name__)
    self._nffgs = dict()
    self._last = None

  def save (self, nffg):
    """
    Save NF-FG in a dict.

    :param nffg: Network Function Forwarding Graph
    :type nffg: :class:`NFFG`
    :return: generated ID of given NF-FG
    :rtype: int
    """
    nffg_id = nffg.id
    self._nffgs[nffg_id] = nffg.copy()
    self._last = nffg
    log.debug("NF-FG: %s is saved by %s with id: %s" %
              (nffg, self.__class__.__name__, nffg_id))
    return nffg_id

  def get_last_request (self):
    """
    Return with the last saved :class:`NFFG`:

    :return: last saved NFFG
    :rtype: :class:`NFFG`
    """
    return self._last

  def get (self, nffg_id):
    """
    Return NF-FG with given id.

    :param nffg_id: ID of NF-FG
    :type nffg_id: int or str
    :return: NF-Fg instance
    :rtype: :class:`NFFG`
    """
    return self._nffgs.get(nffg_id, None)

  def __len__ (self):
    return len(self._nffgs)
