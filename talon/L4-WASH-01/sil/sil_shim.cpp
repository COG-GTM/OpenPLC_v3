//-----------------------------------------------------------------------------
// SIL shim for OpenPLC-compiled IEC 61131-3 programs.
//
// Links against the MatIEC output (POUS.c, Res0.c, Config0.c) and the
// glue_generator output (glueVars.cpp) exactly as the runtime does, but replaces
// main.cpp / the hardware layer / the protocol stacks with a handful of C entry
// points so the control logic can be driven scan-by-scan from Python.
//
// Simulated time: __CURRENT_TIME is advanced by common_ticktime__ after every
// scan (same as the runtime's updateTime()), so a 90 s wash timer is 1800 scans
// and runs in a few milliseconds. Nothing here sleeps.
//-----------------------------------------------------------------------------
#include <cstring>
#include "iec_std_lib.h"

#define BUFFER_SIZE 1024

// MatIEC output is compiled with g++ like the runtime does, so these are C++ symbols.
void config_init__(void);
void config_run__(unsigned long tick);
void glueVars();
void updateTime();

extern TIME __CURRENT_TIME;
extern unsigned long long common_ticktime__;

extern IEC_BOOL *bool_input[BUFFER_SIZE][8];
extern IEC_BOOL *bool_output[BUFFER_SIZE][8];
extern IEC_UINT *int_input[BUFFER_SIZE];
extern IEC_UINT *int_output[BUFFER_SIZE];
extern IEC_UINT *int_memory[BUFFER_SIZE];
extern IEC_UDINT *dint_memory[BUFFER_SIZE];

static unsigned long g_tick = 0;

extern "C" {

// (Re)initialise the program: every located and internal variable, including
// function block instances and timers, goes back to its declared initial value.
void sil_init(void)
{
    config_init__();
    glueVars();
    g_tick = 0;
    __CURRENT_TIME.tv_sec = 0;
    __CURRENT_TIME.tv_nsec = 0;
}

// Execute n PLC scans. Inputs are read as they are at the time of the call
// (the caller owns the input image), outputs are available immediately after.
void sil_scan(unsigned int n)
{
    for (unsigned int i = 0; i < n; i++) {
        config_run__(g_tick++);
        updateTime();
    }
}

unsigned long long sil_ticktime_ns(void) { return common_ticktime__; }
unsigned long sil_tick(void) { return g_tick; }
long long sil_time_ms(void)
{
    return (long long)__CURRENT_TIME.tv_sec * 1000LL + __CURRENT_TIME.tv_nsec / 1000000LL;
}

// ---- %IX  -------------------------------------------------------------------
int sil_set_ix(unsigned int byte, unsigned int bit, int value)
{
    if (byte >= BUFFER_SIZE || bit >= 8 || bool_input[byte][bit] == NULL) return -1;
    *bool_input[byte][bit] = value ? 1 : 0;
    return 0;
}
int sil_get_ix(unsigned int byte, unsigned int bit)
{
    if (byte >= BUFFER_SIZE || bit >= 8 || bool_input[byte][bit] == NULL) return -1;
    return *bool_input[byte][bit] ? 1 : 0;
}

// ---- %QX --------------------------------------------------------------------
int sil_get_qx(unsigned int byte, unsigned int bit)
{
    if (byte >= BUFFER_SIZE || bit >= 8 || bool_output[byte][bit] == NULL) return -1;
    return *bool_output[byte][bit] ? 1 : 0;
}

// ---- %IW / %QW / %MW  (16 bit, returned as signed so INT-typed tags read naturally)
int sil_set_iw(unsigned int idx, int value)
{
    if (idx >= BUFFER_SIZE || int_input[idx] == NULL) return -1;
    *int_input[idx] = (IEC_UINT)value;
    return 0;
}
int sil_get_iw(unsigned int idx, int *out)
{
    if (idx >= BUFFER_SIZE || int_input[idx] == NULL) return -1;
    *out = (IEC_INT)*int_input[idx];
    return 0;
}
int sil_get_qw(unsigned int idx, int *out)
{
    if (idx >= BUFFER_SIZE || int_output[idx] == NULL) return -1;
    *out = (IEC_INT)*int_output[idx];
    return 0;
}
int sil_set_mw(unsigned int idx, int value)
{
    if (idx >= BUFFER_SIZE || int_memory[idx] == NULL) return -1;
    *int_memory[idx] = (IEC_UINT)value;
    return 0;
}
int sil_get_mw(unsigned int idx, int *out)
{
    if (idx >= BUFFER_SIZE || int_memory[idx] == NULL) return -1;
    *out = (IEC_INT)*int_memory[idx];
    return 0;
}

} // extern "C"
