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
import repr

from escape.orchest import LAYER_NAME
from escape.orchest import log as log  # Orchestration layer logger
from escape.orchest.resource_orchestration import ResourceOrchestrator
from escape.util.api import AbstractAPI
from escape.util.misc import schedule_as_coop_task
from escape.util.nffg import NFFG
from pox.lib.revent.revent import Event


class InstallNFFGEvent(Event):
  """
  Dummy event to force dependency checking working
  Should/Will be removed shortly!
  """

  def __init__ (self, mapped_nffg):
    super(InstallNFFGEvent, self).__init__()
    self.mapped_nffg = mapped_nffg


class VirtResInfoEvent(Event):
  """
  Event for sending back requested virtual resource info
  """

  def __init__ (self, resource_info):
    super(VirtResInfoEvent, self).__init__()
    self.resource_info = resource_info


class ResourceOrchestrationAPI(AbstractAPI):
  """
  Entry point for Resource Orchestration Sublayer

  Maintain the contact with other UNIFY layers
  Implement the Sl - Or reference point
  """
  # Define specific name for core object i.e. pox.core.<_core_name>
  _core_name = LAYER_NAME
  # Events raised by this class
  _eventMixin_events = {InstallNFFGEvent, VirtResInfoEvent}
  # Dependencies
  _dependencies = ('adaptation',)

  def __init__ (self, standalone=False, **kwargs):
    log.info("Starting Resource Orchestration Layer...")
    # Mandatory super() call
    super(ResourceOrchestrationAPI, self).__init__(standalone=standalone,
                                                   **kwargs)

  def initialize (self):
    """
    Called when every componenet on which depends are initialized and registered
    in pox.core. Contain actual initialization steps.
    """
    log.debug("Initializing Resource Orchestration Layer...")
    self.resource_orchestrator = ResourceOrchestrator()
    if self.nffg_file:
      self._read_json_from_file(self.nffg_file)
    log.info("Resource Orchestration Layer has been initialized!")

  def shutdown (self, event):
    log.info("Resource Orchestration Layer is going down...")

  # UNIFY Sl- Or API functions starts here

  @schedule_as_coop_task
  def _handle_InstantiateNFFGEvent (self, event):
    """
    Instantiate given NF-FG

    :param event: event object contains NF-FG
    """
    log.getChild('API').info("Received NF-FG from Service layer")
    log.getChild('API').info("Invoke instantiate_nffg on %s with NF-FG: %s " % (
      self.__class__.__name__, repr.repr(event.nffg)))
    mapped_nffg = self.resource_orchestrator.instantiate_nffg(event.nffg)
    log.getChild('API').debug(
      "Invoked instantiate_nffg on %s is finished" % self.__class__.__name__)
    # Sending NF-FG to Adaptation layer as an Event
    # Exceptions in event handlers are caugth by default in a non-blocking way
    self.raiseEventNoErrors(InstallNFFGEvent, mapped_nffg)
    log.getChild('API').info("Mapped NF-FG has been sent to Adaptation...\n")

  def _handle_GetVirtResInfoEvent (self, event):
    """
    Generate virtual resource info and send back to Service layer
    """
    log.getChild('API').debug(
      "Received virtual resource info request from Service layer")
    # TODO - implement - responded data should be deap copied
    # response dummy NFFG
    log.getChild('API').debug("Sending back virtual resource info...\n")
    self.raiseEventNoErrors(VirtResInfoEvent, NFFG())