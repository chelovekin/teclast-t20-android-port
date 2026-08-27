#!/usr/bin/env python3
import re
import sys
from pathlib import Path


if len(sys.argv) != 2:
    raise SystemExit("usage: fix_s5k3l9_pdaf.py <s5k3l9otp.c>")

p = Path(sys.argv[1])
s = p.read_text()
call = "S5K3L9_Read_PDAF_Otp(ui4_length, pinputdata);"

if call not in s:
    pattern = re.compile(
        r"^(?P<line_indent>[ \t]*)else[ \t]+if[ \t]*\([ \t]*ui4_length[ \t]*==[ \t]*"
        r"S5K3L9_LSC_OTP_SIZE[ \t]*\)[ \t]*\r?\n"
        r"(?P<brace_indent>[ \t]*)\{",
        re.MULTILINE,
    )

    def repl(m: re.Match) -> str:
        li = m.group("line_indent")
        bi = m.group("brace_indent")
        return (
            f"{li}else if(ui4_length == S5K3L9_PDAF_OTP_SIZE)\n"
            f"{bi}{{\n"
            f"{bi}\t{call}\n"
            f"{bi}}}\n"
            f"{li}else if(ui4_length == S5K3L9_LSC_OTP_SIZE)\n"
            f"{bi}{{"
        )

    s, count = pattern.subn(repl, s, count=1)
    if count != 1:
        raise RuntimeError("could not locate S5K3L9 LSC branch for PDAF integration")

if s.count(call) != 1:
    raise RuntimeError(f"unexpected S5K3L9 PDAF call count: {s.count(call)}")

p.write_text(s)

# The S5K3L9 sensor implementation is an older MT6795 donor.  Pull only the
# compatibility pieces it needs to compile against the Android-8 MT6797 camera
# framework; sensor register tables and calibration payloads remain untouched.
sensor_p = p.with_name("s5k3l9mipiraw_Sensor.c")
sensor = sensor_p.read_text()

# MT6797 keeps the KAL/UINT/BYTE camera ABI in this header.  The donor relied
# on another include to provide it indirectly, which is not true in this tree.
if '#include "kd_camera_typedef.h"' not in sensor:
    needle = '#include "kd_camera_hw.h"'
    if needle not in sensor:
        raise RuntimeError("could not locate S5K3L9 camera include block")
    sensor = sensor.replace(
        needle,
        '#include "kd_camera_typedef.h"\n' + needle,
        1,
    )

# Linux 3.18 is built with -Werror=strict-prototypes.  These are genuine
# zero-argument functions, so make the prototypes explicit rather than
# weakening warning policy for the whole kernel.
prototype_fixes = {
    "static void set_dummy()": "static void set_dummy(void)",
    "static void hs_video_setting()": "static void hs_video_setting(void)",
    "static void hs_video_setting720P()": "static void hs_video_setting720P(void)",
    "static void slim_video_setting1080P()": "static void slim_video_setting1080P(void)",
    "static void slim_video_setting()": "static void slim_video_setting(void)",
    "extern void read_s5k3l9_static_otp();": "extern void read_s5k3l9_static_otp(void);",
}
for old, new in prototype_fixes.items():
    if old in sensor:
        sensor = sensor.replace(old, new)
    elif new not in sensor:
        raise RuntimeError(f"expected S5K3L9 prototype not found: {old}")

# The MT6795 phone donor carried a local board-revision GPIO helper.  Its only
# call is commented out; the active path uses get_3l9_dvt_id() from s5k3l9otp.c.
# Drop that dead phone-board code instead of importing unrelated GPIO policy.
board_helper = re.compile(
    r'static char \*hwid_string\[\].*?'
    r'static int target_get_board_hwid_no\(void\)\s*\{.*?\n\}\s*\n'
    r'extern int get_3l9_dvt_id\(void\);',
    re.DOTALL,
)
sensor, board_count = board_helper.subn(
    'extern int get_3l9_dvt_id(void);', sensor, count=1
)
if board_count != 1 and 'target_get_board_hwid_no' in sensor:
    raise RuntimeError("could not remove unused S5K3L9 donor board-ID helper")

# Keep declarations at the start of the C90 block.  The donor put this one
# after LOG_INF(), which is rejected by the MTK kernel warning policy.
old_get_info = (
    '\tLOG_INF("scenario_id = %d\\n", scenario_id);\n'
    '\tint hwid_num = 0;\n'
)
new_get_info = (
    '\tint hwid_num = 0;\n\n'
    '\tLOG_INF("scenario_id = %d\\n", scenario_id);\n'
)
if old_get_info in sensor:
    sensor = sensor.replace(old_get_info, new_get_info, 1)
elif new_get_info not in sensor:
    raise RuntimeError("could not normalize S5K3L9 get_info C90 declaration")

# Remove LeEco-specific autofocus-module gating.  T20 must identify the camera
# by the S5K3L9 sensor itself; the BU6429/LC898217 symbols do not exist in the
# MT6797 tablet tree.  Preserve the S5K3L9 static OTP read on a valid sensor.
sensor = sensor.replace('extern kal_bool BU6429_Alive(void);\n', '')
sensor = sensor.replace('extern int Main_Camera_MID;// \n', '')
sensor = sensor.replace('extern int LC898217AF_Init_Thread(void *unused);\n', '')
sensor = sensor.replace('extern struct task_struct  *lc898217af_init_thread;\n', '')
sensor = sensor.replace('extern int g_s4LC898217AF_Inited;\n', '')

module_gate = re.compile(
    r'(?P<i>[ \t]*)if\(BU6429_Alive\(\) == FALSE\)\s*\{.*?'
    r'return ERROR_NONE;\s*\}\s*else\s*\{.*?'
    r'return ERROR_SENSOR_CONNECT_FAIL;\s*\}',
    re.DOTALL,
)

def replace_module_gate(m: re.Match) -> str:
    i = m.group('i')
    return (
        f'{i}read_s5k3l9_static_otp();\n'
        f'{i}*sensor_id = S5K3L9_SENSOR_ID;\n'
        f'{i}return ERROR_NONE;'
    )

sensor, gate_count = module_gate.subn(replace_module_gate, sensor, count=1)
if gate_count != 1 and 'BU6429_Alive' in sensor:
    raise RuntimeError("could not remove S5K3L9 donor autofocus-module gate")

sensor, thread_count = re.subn(
    r'^[ \t]*lc898217af_init_thread\s*=\s*kthread_run\('
    r'LC898217AF_Init_Thread,\s*0,\s*"LC898217AF_Init"\);[ \t]*\r?\n?',
    '',
    sensor,
    count=1,
    flags=re.MULTILINE,
)
if thread_count != 1 and ('LC898217AF_Init_Thread' in sensor or 'lc898217af_init_thread' in sensor):
    raise RuntimeError("could not remove S5K3L9 donor autofocus init thread")

sensor_p.write_text(sensor)
print("S5K3L9 PDAF OTP read path wired into CAM_CAL dispatcher", flush=True)
print("S5K3L9 sensor donor adapted to MT6797 camera ABI", flush=True)
