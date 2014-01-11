#
# preferences.py
#
# Copyright (C) 2014 Ratanak Lun <ratanakvlun@gmail.com>
# Copyright (C) 2008 Martijn Voncken <mvoncken@gmail.com>
#
# Deluge is free software.
#
#
# You may redistribute it and/or modify it under the terms of the
# GNU General Public License, as published by the Free Software
# Foundation; either version 3 of the License, or (at your option)
# any later version.
#
# deluge is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with deluge.    If not, write to:
# 	The Free Software Foundation, Inc.,
# 	51 Franklin Street, Fifth Floor
# 	Boston, MA  02110-1301, USA.
#
#    In addition, as a special exception, the copyright holders give
#    permission to link the code of portions of this program with the OpenSSL
#    library.
#    You must obey the GNU General Public License in all respects for all of
#    the code used other than OpenSSL. If you modify file(s) with this
#    exception, you may extend this exception to your version of the file(s),
#    but you are not obligated to do so. If you do not wish to do so, delete
#    this exception statement from your version. If you delete this exception
#    statement from all source files in the program, then also delete it here.
#


import copy
import os.path
import gtk

from twisted.internet import reactor

from deluge import component
from deluge.ui.client import client
import deluge.configmanager

from labelplus.common.constant import PLUGIN_NAME
from labelplus.common.constant import DISPLAY_NAME
from labelplus.common.constant import OPTION_DEFAULTS
from labelplus.common.constant import LABEL_DEFAULTS

from common.constant import GTKUI_DEFAULTS

from labelplus.common.file import get_resource
from labelplus.common.debug import debug

from util import textview_set_text
from util import textview_get_text
from widget_encapsulator import WidgetEncapsulator


OP_MAP = {
  gtk.RadioButton: ("set_active", "get_active"),
  gtk.CheckButton: ("set_active", "get_active"),
  gtk.SpinButton: ("set_value", "get_value"),
  gtk.Label: ("set_text", "get_text"),
}


class Preferences(object):


  def __init__(self):

    self.config = component.get("GtkPlugin." + PLUGIN_NAME)._config

    self.plugin = component.get("PluginManager")
    self.we = WidgetEncapsulator(get_resource("wnd_preferences.glade"))
    self.daemon_is_local = client.is_localhost()
    self.last_prefs = None
    self._saving = False

    self.header_widgets = (
      self.we.lbl_general,
      self.we.lbl_shared_limit,
      self.we.lbl_defaults,
    )

    self.general_widgets = (
      self.we.chk_include_children,
      self.we.chk_show_full_name,
      self.we.chk_move_on_changes,
      self.we.chk_autolabel_uses_regex,
      self.we.spn_shared_limit_update_interval,
      self.we.chk_move_after_recheck,
    )

    self.defaults_widgets = (
      self.we.chk_download_settings,
      self.we.chk_move_data_completed,
      self.we.chk_prioritize_first_last,

      self.we.chk_bandwidth_settings,
      self.we.rb_shared_limit_on,
      self.we.spn_max_download_speed,
      self.we.spn_max_upload_speed,
      self.we.spn_max_connections,
      self.we.spn_max_upload_slots,

      self.we.chk_queue_settings,
      self.we.chk_auto_managed,
      self.we.chk_stop_at_ratio,
      self.we.spn_stop_ratio,
      self.we.chk_remove_at_ratio,

      self.we.chk_auto_settings,
      self.we.rb_auto_name,
      self.we.rb_auto_tracker,
    )

    self.rgrp_move_data_completed = (
      self.we.rb_move_data_completed_to_parent,
      self.we.rb_move_data_completed_to_subfolder,
      self.we.rb_move_data_completed_to_folder,
    )

    self.exp_group = (
      self.we.exp_download,
      self.we.exp_bandwidth,
      self.we.exp_queue,
      self.we.exp_autolabel,
    )

    expanded = self.config["common"]["prefs_state"]
    for exp in expanded:
      widget = getattr(self.we, exp, None)
      if widget:
        widget.set_expanded(True)

    for header in self.header_widgets:
      heading = header.get_text()
      header.set_markup("<b>%s</b>" % heading)

    self.we.btn_defaults.connect("clicked", self._reset_preferences)

    if self.daemon_is_local:
      self.we.fcb_move_data_completed_select.show()
      self.we.txt_move_data_completed_entry.hide()
    else:
      self.we.fcb_move_data_completed_select.hide()
      self.we.txt_move_data_completed_entry.show()

    self.we.blk_preferences.connect("expose-event", self._do_set_unavailable)

    self.plugin.add_preferences_page(DISPLAY_NAME, self.we.blk_preferences)
    self.plugin.register_hook("on_show_prefs", self._load_settings)
    self.plugin.register_hook("on_apply_prefs", self._save_settings)

    self._load_settings()


  def unload(self):

    self.plugin.deregister_hook("on_apply_prefs", self._save_settings)
    self.plugin.deregister_hook("on_show_prefs", self._load_settings)
    self.plugin.remove_preferences_page(DISPLAY_NAME)


  @debug()
  def _reset_preferences(self, widget):

    self._load_general(OPTION_DEFAULTS)
    self._load_defaults(LABEL_DEFAULTS)

    self.we.chk_show_label_bandwidth.set_active(
      GTKUI_DEFAULTS["common"]["show_label_bandwidth"])


  def _do_set_unavailable(self, widget, event):

    flag = "MoveTools" in self.plugin.get_enabled_plugins()
    self.we.chk_move_on_changes.set_sensitive(flag)
    self.we.chk_move_after_recheck.set_sensitive(flag)

    if flag:
      self.we.chk_move_on_changes.set_tooltip_text(None)
      self.we.chk_move_after_recheck.set_tooltip_text(None)
    else:
      require_message = _("Requires Move Tools plugin")
      self.we.chk_move_on_changes.set_tooltip_text(require_message)
      self.we.chk_move_after_recheck.set_tooltip_text(require_message)


  def _load_settings(self, widget=None, data=None):

    if not self._saving:
      self.last_prefs = None
      client.labelplus.get_preferences().addCallback(self._do_load)
    else:
      reactor.callLater(0.1, self._load_settings)


  @debug()
  def _save_settings(self):

    self._saving = True

    general = self._get_general()
    defaults = self._get_defaults()

    if self.last_prefs:
      need_save = False

      for k, v in general.iteritems():
        if self.last_prefs["options"].get(k) != v:
          need_save = True
          break

      if not need_save:
        for k, v in defaults.iteritems():
          if self.last_prefs["defaults"].get(k) != v:
            need_save = True
            break
    else:
      need_save = True

    if need_save:
      prefs = {
        "options": general,
        "defaults": defaults,
      }

      client.labelplus.set_preferences(prefs).addCallbacks(
        self._on_save_done, self._on_save_done)
      self.last_prefs = prefs

    expanded = []
    for exp in self.exp_group:
      if exp.get_expanded():
        expanded.append(exp.get_name())

    self.config["common"]["show_label_bandwidth"] = \
      self.we.chk_show_label_bandwidth.get_active()

    self.config["common"]["prefs_state"] = expanded
    self.config.save()

    if not need_save:
      self._saving = False


  @debug()
  def _do_load(self, prefs):

    self.last_prefs = prefs

    general = prefs["options"]
    defaults = prefs["defaults"]

    self._load_general(general)
    self._load_defaults(defaults)

    self.we.chk_show_label_bandwidth.set_active(
      self.config["common"]["show_label_bandwidth"])


  def _on_save_done(self, result):

    self._saving = False


  def _load_general(self, general):

    options = copy.deepcopy(OPTION_DEFAULTS)
    options.update(general)

    for widget in self.general_widgets:
      prefix, sep, name = widget.get_name().partition("_")
      if sep and name in options:
        widget_type = type(widget)
        if widget_type in OP_MAP:
          setter = getattr(widget, OP_MAP[widget_type][0])
          setter(options[name])


  def _get_general(self):

    options = copy.deepcopy(OPTION_DEFAULTS)

    for widget in self.general_widgets:
      prefix, sep, name = widget.get_name().partition("_")
      if sep and name in options:
        widget_type = type(widget)
        if widget_type in OP_MAP:
          getter = getattr(widget, OP_MAP[widget_type][1])
          options[name] = getter()

    return options


  def _load_defaults(self, defaults):

    options = copy.deepcopy(LABEL_DEFAULTS)
    options.update(defaults)

    for widget in self.defaults_widgets:
      prefix, sep, name = widget.get_name().partition("_")
      if sep and name in options:
        widget_type = type(widget)
        if widget_type in OP_MAP:
          setter = getattr(widget, OP_MAP[widget_type][0])
          setter(options[name])

    rb = getattr(self.we, "rb_move_data_completed_to_%s" %
        options["move_data_completed_mode"])
    rb.set_active(True)

    if options["shared_limit_on"]:
      self.we.rb_shared_limit_on.set_active(True)
    else:
      self.we.rb_shared_limit_off.set_active(True)

    path = options["move_data_completed_path"]
    if not path:
      core_config = getattr(component.get("Preferences"), "core_config", None)
      if core_config:
        path = core_config.get("move_completed_path", "")

    if self.daemon_is_local:
      if not os.path.exists(path):
        path = ""

      self.we.fcb_move_data_completed_select.unselect_all()
      self.we.fcb_move_data_completed_select.set_filename(path)
    else:
      self.we.txt_move_data_completed_entry.set_text(path)

    textview_set_text(self.we.tv_auto_queries,
        "\n".join(options["auto_queries"]))


  def _get_defaults(self):

    options = copy.deepcopy(LABEL_DEFAULTS)

    for widget in self.defaults_widgets:
      prefix, sep, name = widget.get_name().partition("_")
      if sep and name in options:
        widget_type = type(widget)
        if widget_type in OP_MAP:
          getter = getattr(widget, OP_MAP[widget_type][1])
          options[name] = getter()

    options["max_upload_slots"] = int(options["max_upload_slots"])
    options["max_connections"] = int(options["max_connections"])

    for rb in self.rgrp_move_data_completed:
      if rb.get_active():
        prefix, sep, mode = rb.get_name().rpartition("_")
        options["move_data_completed_mode"] = mode
        break

    if self.daemon_is_local:
      path = self.we.fcb_move_data_completed_select.get_filename()
    else:
      path = self.we.txt_move_data_completed_entry.get_text().strip()

    options["move_data_completed_path"] = path

    lines = textview_get_text(self.we.tv_auto_queries).split("\n")
    options["auto_queries"] = tuple(x.strip() for x in lines if x.strip())

    return options
