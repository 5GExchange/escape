# Copyright 2015 Janos Czentye
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
Contains classes which implement SG mapping functionality

:class:`DefaultServiceMappingStrategy` implements a default mapping algorithm
which map given SG on a single Bis-Bis

:class:`ServiceGraphMapper` perform the supplementary tasks for SG mapping
"""
import threading

from escape.util.mapping import AbstractMappingStrategy, AbstractMapper
from escape.service import log as log
from escape import CONFIG
from escape.util.misc import call_as_coop_task
from pox.lib.revent.revent import Event


class DefaultServiceMappingStrategy(AbstractMappingStrategy):
  """
  Mapping class which maps given Service Graph into a single BiS-BiS
  """

  def __init__ (self):
    """
    Init
    """
    super(DefaultServiceMappingStrategy, self).__init__()

  @classmethod
  def map (cls, graph, resource):
    """
    Default mapping algorithm which maps given Service Graph on one BiS-BiS

    :param graph: Service Graph
    :type graph: NFFG
    :param resource: virtual resource
    :type resource: NFFG
    :return: Network Function Forwarding Graph
    :rtype: NFFG
    """
    log.debug(
      "Invoke mapping algorithm: %s on SG(%s)" % (cls.__name__, graph.id))
    # TODO implement
    log.debug(
      "Mapping algorithm: %s is finished on SG(%s)" % (cls.__name__, graph.id))
    # for testing return with graph
    return graph


class SGMappingFinishedEvent(Event):
  """
  Event for signaling the end of SG mapping
  """

  def __init__ (self, nffg):
    """
    Init

    :param nffg: NF-FG need to be initiated
    :type nffg: NFFG
    """
    super(SGMappingFinishedEvent, self).__init__()
    self.nffg = nffg


class ServiceGraphMapper(AbstractMapper):
  """
  Helper class for mapping Service Graph to NF-FG
  """
  # Events raised by this class
  _eventMixin_events = {SGMappingFinishedEvent}

  def __init__ (self, strategy=DefaultServiceMappingStrategy, threaded=True):
    """
    Init mapper class

    :param strategy: mapping strategy (default DefaultServiceMappingStrategy)
    :type strategy: AbstractMappingStrategy
    :param threaded: run mapping algorithm in a separate Python thread
    :type threaded: bool
    :return: None
    """
    self._threaded = threaded
    if hasattr(CONFIG['SAS'], 'STRATEGY'):
      if issubclass(CONFIG['SAS']['STRATEGY'], AbstractMappingStrategy):
        try:
          strategy = getattr(self.__module__, CONFIG['SAS']['STRATEGY'])
        except AttributeError:
          log.warning(
            "Mapping strategy: %s is not found in module: %s, fall back to "
            "%s" % (
              CONFIG['SAS']['STRATEGY'], self.__module__, strategy.__name__))
      else:
        log.warning(
          "SAS mapping strategy is not subclass of AbstractMappingStrategy, "
          "fall back to %s" % strategy.__name__)
    super(ServiceGraphMapper, self).__init__(strategy)
    log.debug("Init %s with strategy: %s" % (
      self.__class__.__name__, strategy.__name__))

  def orchestrate (self, input_graph, resource_view):
    """
    Orchestrate mapping of given service graph on given virtual resource

    :param input_graph: Service Graph
    :type input_graph: NFFG
    :param resource_view: virtual resource view
    :param resource_view: ESCAPEVirtualizer
    :return: Network Function Forwarding Graph
    :rtype: NFFG
    """
    log.debug("Request %s to launch orchestration on SG(%s)..." % (
      self.__class__.__name__, input_graph.id))
    # Steps before mapping (optional)
    virt_resource = resource_view.get_resource_info()
    resource_view.sanity_check(input_graph)
    # Run actual mapping algorithm
    if self._threaded:
      # Schedule a microtask which run mapping algorithm in a Python thread
      log.info(
        "Schedule mapping algorithm: %s in a worker thread" %
        self.strategy.__name__)
      call_as_coop_task(self._start_mapping, graph=input_graph,
                        resource=virt_resource)
      log.info("SG(%s) orchestration is finished by %s" % (
        input_graph.id, self.__class__.__name__))
    else:
      nffg = self.strategy.map(graph=input_graph, resource=virt_resource)
      # Steps after mapping (optional)
      log.info("SG(%s) orchestration is finished by %s" % (
        input_graph.id, self.__class__.__name__))
      return nffg

  def _start_mapping (self, graph, resource):
    """
    Run mapping algorithm in a separate Python thread

    :param graph: Service Graph
    :type graph: NFFG
    :param resource: virtual resource
    :type resource: NFFG
    :return: None
    """

    def run ():
      log.info("Schedule mapping algorithm: %s" % self.strategy.__name__)
      nffg = self.strategy.map(graph=graph, resource=resource)
      # Must use call_as_coop_task because we want to call a function in a
      # coop microtask environment from a separate thread
      call_as_coop_task(self._mapping_finished, nffg=nffg)

    log.debug("Initialize working thread...")
    self._mapping_thread = threading.Thread(target=run)
    self._mapping_thread.daemon = True
    self._mapping_thread.start()

  def _mapping_finished (self, nffg):
    """
    Called from a separate thread when the mapping process is finished

    :param nffg: geenrated NF-FG
    :type nffg: NFFG
    :return: None
    """
    log.debug("Inform layer API that SG mapping has been finished...")
    self.raiseEventNoErrors(SGMappingFinishedEvent, nffg)