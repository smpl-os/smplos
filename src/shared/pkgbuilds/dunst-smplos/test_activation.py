"""Synthetic tests; no connection to the user's bus or compositor."""

import ctypes
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent
loader = importlib.machinery.SourceFileLoader(
    "signal_activation", str(ROOT / "signal-notification-activate"))
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.bus = mock.Mock()
        self.bus.owner.return_value = ":1.10"
        self.bus.pid.side_effect = lambda name: {":1.10": 100, ":1.20": 200}[name]
        self.process = mock.patch.object(helper, "process", return_value=(100, "1234"))
        self.process.start()
        self.addCleanup(self.process.stop)
        self.parent = mock.patch.object(helper.os, "getppid", return_value=100)
        self.parent.start()
        self.addCleanup(self.parent.stop)
        self.dispatch = mock.Mock()

    def test_owner_parent_and_recipient_admitted(self):
        helper.prepare(":1.20", self.bus, self.dispatch)
        self.dispatch.assert_called_once_with(
            os.getpid(), "1234", 100, "1234", 200, "1234")

    def test_ordinary_invocation_cannot_supply_a_recipient(self):
        self.bus.pid.side_effect = lambda name: 999
        with self.assertRaisesRegex(ValueError, "not notification owner"):
            helper.prepare(":1.20", self.bus, self.dispatch)
        self.dispatch.assert_not_called()

    def test_owner_change_recipient_change_parent_change_and_pid_reuse(self):
        cases = (
            ("owner", lambda: setattr(self.bus.owner, "side_effect", [":1.10", ":1.11"])),
            ("recipient", lambda: setattr(self.bus.pid, "side_effect", [100, 200, 100, 201])),
            ("parent", lambda: setattr(helper.os.getppid, "side_effect", [100, 101])),
            ("identity", lambda: setattr(helper.process, "side_effect",
                                        [(100, "1"), (100, "1"), (100, "1"), (100, "2")])),
        )
        for name, setup in cases:
            with self.subTest(case=name):
                self.bus.owner.side_effect = None
                self.bus.pid.side_effect = lambda n: {":1.10": 100, ":1.20": 200}[n]
                helper.os.getppid.side_effect = None
                helper.process.side_effect = None
                setup()
                with self.assertRaises(ValueError):
                    helper.prepare(":1.20", self.bus, self.dispatch)
                self.dispatch.assert_not_called()

    def test_stale_recipient_is_not_dispatched(self):
        self.bus.pid.side_effect = [100, ValueError("stale")]
        with self.assertRaises(ValueError):
            helper.prepare(":1.20", self.bus, self.dispatch)
        self.dispatch.assert_not_called()

    def test_bad_unique_names_rejected_without_bus_queries(self):
        for name in ("", "org.signal.Signal", ":1.2;bad", ":1.2\n"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                helper.prepare(name, self.bus, self.dispatch)
        self.bus.owner.assert_not_called()

    def test_bus_cannot_autolaunch_or_use_alternate_or_network_transport(self):
        for address in ("", "tcp:host=localhost", "autolaunch:",
                        "unix:path=/tmp/synthetic;autolaunch:"):
            with self.subTest(address=address), \
                    mock.patch.dict(os.environ, {"DBUS_SESSION_BUS_ADDRESS": address}), \
                    mock.patch.object(helper.C, "CDLL") as library:
                with self.assertRaises(ValueError):
                    helper.Bus()
                library.assert_not_called()

    def test_compositor_requires_exact_completed_acknowledgment(self):
        for reply, accepted in ((b"ok", True), (b"false", False), (b"error", False)):
            with self.subTest(reply=reply), \
                    mock.patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "test_only"}), \
                    mock.patch.object(helper.socket, "socket") as socket:
                connection = socket.return_value.__enter__.return_value
                connection.recv.side_effect = [reply, b""]
                if accepted:
                    helper.dispatch(10, "20", 30, "40", 50, "60")
                else:
                    with self.assertRaises(ValueError):
                        helper.dispatch(10, "20", 30, "40", 50, "60")
                sent = connection.sendall.call_args.args[0]
                self.assertTrue(sent.startswith(b"eval assert(loadfile("))
                self.assertNotIn(b"exec", sent)


class PrivateBusTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("dbus-daemon"), "needs private dbus-daemon")
    def test_real_libdbus_typed_identity_queries_only_on_private_bus(self):
        with tempfile.TemporaryDirectory() as temp:
            daemon = subprocess.Popen(
                ["dbus-daemon", "--session", "--nofork", "--nopidfile",
                 "--print-address", "--address=unix:path=" + temp + "/bus"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                address = daemon.stdout.readline().strip()
                self.assertTrue(address.startswith("unix:path="))
                with mock.patch.dict(os.environ, {"DBUS_SESSION_BUS_ADDRESS": address}):
                    bus = helper.Bus()
                    try:
                        fn = bus.lib.dbus_bus_get_unique_name
                        fn.restype, fn.argtypes = ctypes.c_char_p, [ctypes.c_void_p]
                        name = fn(bus.connection).decode()
                        self.assertEqual(os.getpid(), bus.pid(name))
                        self.assertEqual(name, bus.query("GetNameOwner", name, "s"))
                        with self.assertRaises(ValueError):
                            bus.owner()
                    finally:
                        bus.close()
            finally:
                daemon.terminate()
                daemon.communicate(timeout=5)


LUA_FIXTURE = r"""
local case, script = arg[1], arg[2]
local events, alive, helper_state, start = {}, true, "S", "1234"
local target_monitor, old_monitor = {id=1}, {id=2}
local target = {id=2, special=false, monitor=target_monitor}
local old = {id=case == "normal" and 3 or -98, special=case ~= "normal",
             monitor=old_monitor, is_empty=false, windows=1}
local other = {address="0x1", class="other", pid=42, mapped=true, workspace=target}
local signal = {address="0x2", class="Signal", pid=200, mapped=true, workspace=old}
local unrelated = {address="0x3", class="other", pid=43, mapped=true,
                   workspace={id=4, monitor=old_monitor}}
local windows, active = {other, signal, unrelated}, other
old_monitor.active_special_workspace = old.special and old or nil
function old_monitor:set_special_workspace(value)
    assert(next(value) == nil)
    events[#events+1] = "cleanup"
    self.active_special_workspace = nil
end
if case == "already_signal" or case == "grouped_on_target" or case == "swallowing_on_target" then
    old.id, old.special = 3, false
    target, active = old, signal
    old_monitor.active_special_workspace = nil
    if case == "grouped_on_target" then signal.group = {} end
    if case == "swallowing_on_target" then signal.swallowing = unrelated end
end
if case == "special_target" then target.special, target.id = true, -2 end
if case == "no_active" then active = nil end
if case == "grouped" then signal.group = {} end
if case == "pinned" then signal.pinned = true end
if case == "swallowing" then signal.swallowing = unrelated end
if case == "destination_group" then other.group = {} end
if case == "ambiguous" then windows[#windows+1] =
    {class="Signal", pid=200, mapped=true, workspace=old} end
if case == "dead" then alive = false end
if case == "zombie" then helper_state = "Z" end
if case == "reused" then start = "different" end
if case == "nonempty_special" or case == "different_special_nonempty" then
    old.nonempty, old.windows = true, 2
end
if case == "different_special" or case == "different_special_autoclose"
    or case == "different_special_nonempty" then
    old_monitor.active_special_workspace = {id=-77}
end
local auto_close = case == "different_special_autoclose"
    or case == "different_special_nonempty" or case == "native_autoclose"
io.open = function(path)
    if not alive then return nil end
    local pid = assert(path:match("^/proc/(%d+)/stat$"))
    local fields = {pid == "10" and helper_state or "S", pid == "10" and "100" or "1"}
    for i=3,19 do fields[i] = "0" end
    fields[20] = pid == "10" and start or "1234"
    return {read=function() return pid .. " (synthetic process) " .. table.concat(fields," ") end,
            close=function() end}
end
hl = {
 get_windows=function() return windows end,
 get_active_window=function() return active end,
 get_config=function(key)
    if key == "group.group_on_movetoworkspace" then return 1 end
    assert(key == "misc.close_special_on_empty")
    return auto_close
 end,
 dsp={
  window={move=function(value) return function()
    events[#events+1] = "move"
    assert(value.window == signal and value.workspace == 2 and value.silent)
    if case == "move_error" then return {ok=false} end
    if case ~= "move_noop" then signal.workspace=target; old.is_empty=not old.nonempty end
    -- Native Window::moveToWorkspace closes the monitor's special, not necessarily old.
    if old.special and old.is_empty and auto_close then old_monitor:set_special_workspace({}) end
    return {ok=true}
  end end},
  focus=function(value) return function()
    events[#events+1] = "focus"
    assert(value.window == signal)
    if case == "focus_error" then return {ok=false} end
    if case ~= "focus_noop" then active=signal end
    return {ok=true}
  end end,
 },
}
local before = unrelated.workspace
local ok = pcall(assert(loadfile(script))(), 10,"1234",100,"1234",200,"1234")
assert(unrelated.workspace == before and not unrelated.group)
local expected_failure = {special_target=true,no_active=true,grouped=true,pinned=true,swallowing=true,
 destination_group=true,ambiguous=true,dead=true,zombie=true,reused=true,
 move_error=true,move_noop=true,focus_error=true,focus_noop=true,different_special_autoclose=true}
assert(ok ~= (expected_failure[case] == true), case .. " unexpected result")
if expected_failure[case] then
 if case == "move_error" or case == "move_noop" then assert(#events == 1)
 elseif case ~= "focus_error" and case ~= "focus_noop" then assert(#events == 0) end
else
 assert(active == signal and signal.workspace == target)
 if case == "nonempty_special" then assert(old_monitor.active_special_workspace == old)
 elseif case == "different_special" or case == "different_special_nonempty" then
  assert(old_monitor.active_special_workspace.id == -77)
 elseif case ~= "normal" and case ~= "already_signal" and case ~= "grouped_on_target" then
  assert(old_monitor.active_special_workspace == nil)
 end
end
print("ok")
"""


class LuaTests(unittest.TestCase):
    def test_actual_transaction_target_lifetime_grouping_and_exact_effects(self):
        lua = shutil.which("lua") or shutil.which("lua5.4")
        self.assertIsNotNone(lua, "Lua required for Signal transaction tests")
        cases = (
            "special", "normal", "already_signal", "grouped_on_target", "swallowing_on_target",
            "special_target", "no_active", "grouped", "pinned", "swallowing", "destination_group",
            "ambiguous", "dead", "zombie", "reused", "nonempty_special",
            "different_special", "different_special_autoclose", "different_special_nonempty",
            "native_autoclose", "move_error", "move_noop", "focus_error", "focus_noop")
        for case in cases:
            with self.subTest(case=case):
                result = subprocess.run(
                    [lua, "-", case, str(ROOT / "signal-transaction.lua")],
                    input=LUA_FIXTURE, text=True, capture_output=True, timeout=5)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("ok\n", result.stdout)


@unittest.skipUnless(os.environ.get("SMPLOS_DUNST_SOURCE"), "native package check supplies patched Dunst source")
class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.path = Path(cls.temp.name)
        cls.events = cls.path / "events"
        fake = cls.path / "helper"
        fake.write_text(
            "#!/usr/bin/python3\nimport os,sys,time\n"
            "assert len(sys.argv)==2 and sys.argv[1]==':1.20'\n"
            "with open(os.environ['TEST_EVENTS'],'a') as f: f.write('prepare\\n')\n"
            "with open(os.environ['TEST_PID'],'w') as f: f.write(str(os.getpid()))\n"
            "mode=os.environ['TEST_MODE']\n"
            "if mode=='hang': time.sleep(10)\n"
            "if mode=='signal': os.kill(os.getpid(),15)\n"
            "sys.exit(1 if mode=='fail' else 0)\n")
        fake.chmod(0o755)
        source = (Path(os.environ["SMPLOS_DUNST_SOURCE"]) / "src/dbus.c").read_text()
        start = source.index("void signal_action_invoked(")
        end = source.index("\nGVariant *dbus_cb_dunst_Properties_Get", start)
        function = source[start:end]
        assert function.index("if (!n->dbus_valid)") < function.index("smplos_signal_pre_forward(")
        assert function.index("smplos_signal_pre_forward(") < function.index("g_dbus_connection_emit_signal(")
        c = cls.path / "native.c"
        c.write_text(r'''
#include <gio/gio.h>
#include <stdio.h>
#include <signal.h>
#include <sys/wait.h>
#include <unistd.h>
#define LOG_W(...) ((void)0)
static int owned_kill(pid_t pid, int sig) {
    siginfo_t info={0};
    if (waitid(P_PID,pid<0?-pid:pid,&info,WEXITED|WNOHANG|WNOWAIT)<0) _exit(89);
    return kill(pid,sig);
}
#define kill owned_kill
#include "smplos-action.h"
#undef kill
#define FDN_PATH "/org/freedesktop/Notifications"
#define FDN_IFAC "org.freedesktop.Notifications"
struct notification {bool dbus_valid; const char *dbus_client, *appname, *desktop_entry; unsigned id;};
static GDBusConnection *dbus_conn;
static gboolean emit(GDBusConnection *c, const char *d, const char *p, const char *i,
                     const char *s, GVariant *body, GError **err) {
    FILE *pids=fopen(getenv("TEST_PID"),"r"); int pid=0;
    if (pids) { (void)fscanf(pids,"%d",&pid); fclose(pids); }
    if (pid && kill(pid,0)==0) exit(88);
    FILE *f=fopen(getenv("TEST_EVENTS"),"a"); fputs("emit\n",f); fclose(f);
    g_variant_unref(g_variant_ref_sink(body)); return TRUE;
}
#define g_dbus_connection_emit_signal emit
''' + function + r'''
int main(int argc, char **argv) {
    if (strcmp(getenv("TEST_MODE"),"ignored")==0) signal(SIGCHLD,SIG_IGN);
    if (strcmp(getenv("TEST_MODE"),"autoreap")==0) {
        struct sigaction disposition={.sa_handler=SIG_DFL,.sa_flags=SA_NOCLDWAIT};
        sigaction(SIGCHLD,&disposition,NULL);
    }
    struct notification n={atoi(argv[4]),":1.20",argv[2],argv[3],7};
    signal_action_invoked(&n,argv[1]); return 0;
}
''')
        flags = subprocess.check_output(
            ["pkg-config", "--cflags", "--libs", "gio-2.0"], text=True).split()
        subprocess.run(["cc", "-Wall", "-Werror", "-Wno-unused-parameter",
                        "-DSMPLOS_ACTION_TIMEOUT_US=100000",
                        '-DSMPLOS_ACTION_HELPER="' + str(fake) + '"',
                        "-I" + str(ROOT), str(c), "-o", str(cls.path / "native"), *flags],
                       check=True, capture_output=True)

    def test_registered_pre_emit_order_failure_timeout_and_action_filter(self):
        cases = (
            ("ok", "default", "Signal", "", "1", ["prepare", "emit"]),
            ("fail", "default", "Signal", "", "1", ["prepare", "emit"]),
            ("signal", "default", "Signal", "", "1", ["prepare", "emit"]),
            ("hang", "default", "Signal", "", "1", ["prepare", "emit"]),
            ("missing", "default", "Signal", "", "1", ["emit"]),
            ("ignored", "default", "Signal", "", "1", ["emit"]),
            ("autoreap", "default", "Signal", "", "1", ["emit"]),
            ("ok", "0", "Signal", "", "1", ["emit"]),
            ("ok", "mark-read", "Signal", "", "1", ["emit"]),
            ("ok", "default", "other", "", "1", ["emit"]),
            ("ok", "default", "other", "org.signal.Signal", "1", ["prepare", "emit"]),
            ("ok", "default", "Signal", "", "0", []),
        )
        for mode, action, app, desktop, valid, expected in cases:
            with self.subTest(mode=mode, action=action, app=app, valid=valid):
                self.events.write_text("")
                pidfile = self.path / "pid"
                pidfile.write_text("")
                env = {**os.environ, "TEST_MODE": mode, "TEST_EVENTS": str(self.events),
                       "TEST_PID": str(pidfile)}
                executable = self.path / "helper"
                hidden = self.path / "helper-away"
                if mode == "missing":
                    executable.rename(hidden)
                try:
                    subprocess.run([str(self.path / "native"), action, app, desktop, valid],
                                   env=env, check=True, capture_output=True, timeout=3)
                finally:
                    if mode == "missing":
                        hidden.rename(executable)
                self.assertEqual(expected, self.events.read_text().splitlines())
                if mode == "hang":
                    late = subprocess.run(
                        ["lua", "-", str(ROOT / "signal-transaction.lua"), pidfile.read_text()],
                        input='local touched=false; hl={get_windows=function() touched=true end}; '
                              'local ok=pcall(assert(loadfile(arg[1]))(),tonumber(arg[2]),'
                              '"stale",1,"stale",2,"stale"); assert(not ok and not touched)',
                        text=True, capture_output=True, timeout=3)
                    self.assertEqual(0, late.returncode, late.stderr)


if __name__ == "__main__":
    unittest.main()
