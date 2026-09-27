//-----------------------------------------------------------------------------
// Test harness for webserver/core/modbus.cpp (Talon OT security review, F3).
//
// Links modbus.cpp on its own - no main.cpp, no hardware layer, no sockets -
// and supplies the globals the runtime normally gets from glueVars.cpp,
// debug.cpp, main.cpp and utils.cpp. Exposes a handful of C entry points so a
// pytest can hand the frame processor a Modbus/TCP ADU together with a peer
// address and inspect the response and the register image.
//
// Compiled with -DMB_LEGACY_DISPATCH the harness targets the pre-fix runtime
// (processModbusMessage without a peer address) so the same test can be run
// against both revisions.
//-----------------------------------------------------------------------------
#include <arpa/inet.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "ladder.h"

// glueVars.cpp
IEC_BOOL *bool_input[BUFFER_SIZE][8];
IEC_BOOL *bool_output[BUFFER_SIZE][8];
IEC_BYTE *byte_input[BUFFER_SIZE];
IEC_BYTE *byte_output[BUFFER_SIZE];
IEC_UINT *int_input[BUFFER_SIZE];
IEC_UINT *int_output[BUFFER_SIZE];
IEC_UDINT *dint_input[BUFFER_SIZE];
IEC_UDINT *dint_output[BUFFER_SIZE];
IEC_ULINT *lint_input[BUFFER_SIZE];
IEC_ULINT *lint_output[BUFFER_SIZE];
IEC_UINT *int_memory[BUFFER_SIZE];
IEC_UDINT *dint_memory[BUFFER_SIZE];
IEC_ULINT *lint_memory[BUFFER_SIZE];
IEC_ULINT *special_functions[BUFFER_SIZE];
pthread_mutex_t bufferLock = PTHREAD_MUTEX_INITIALIZER;
unsigned long long common_ticktime__ = 50000000ULL;

// main.cpp / debug.cpp
unsigned long __tick = 0;
char md5[] = "00000000000000000000000000000000";

static int g_set_trace_calls = 0;
static int g_force_var_calls = 0;
static uint16_t g_debug_var = 0;

// debug.h - one traced variable so DEBUG_SET has a legal index to hit.
void set_endianness(uint8_t) {}
uint16_t get_var_count(void) { return 1; }
size_t get_var_size(size_t) { return sizeof(g_debug_var); }
void *get_var_addr(size_t) { return &g_debug_var; }
void force_var(size_t, bool, void *) { g_force_var_calls++; }
void set_trace(size_t, bool, void *) { g_set_trace_calls++; }
void trace_reset(void) {}

// utils.cpp
extern "C" void openplc_log(char *logmsg) { fputs(logmsg, stderr); }
void sleepms(int) {}

extern IEC_UINT mb_holding_regs[];

extern "C" {

void harness_init(void)
{
    memset(bool_input, 0, sizeof(bool_input));
    memset(bool_output, 0, sizeof(bool_output));
    memset(int_input, 0, sizeof(int_input));
    memset(int_output, 0, sizeof(int_output));
    memset(int_memory, 0, sizeof(int_memory));
    memset(dint_memory, 0, sizeof(dint_memory));
    memset(lint_memory, 0, sizeof(lint_memory));
    mapUnusedIO();
    for (int i = 0; i < 8192; i++) mb_holding_regs[i] = 0;
    g_set_trace_calls = 0;
    g_force_var_calls = 0;
}

int harness_load_allowlist(const char *path)
{
#ifdef MB_LEGACY_DISPATCH
    (void)path;
    return -1;
#else
    return loadModbusWriteAllowlist(path);
#endif
}

// Process one ADU as if it had arrived from `peer_ip`. Returns response length.
int harness_process(unsigned char *buffer, int size, const char *peer_ip)
{
    struct in_addr peer;
    if (inet_pton(AF_INET, peer_ip, &peer) != 1) return -1;
#ifdef MB_LEGACY_DISPATCH
    return processModbusMessage(buffer, size);
#else
    return processModbusMessage(buffer, size, peer.s_addr);
#endif
}

uint16_t harness_holding_reg(int idx) { return mb_holding_regs[idx]; }
void harness_set_holding_reg(int idx, uint16_t value) { mb_holding_regs[idx] = value; }
int harness_set_trace_calls(void) { return g_set_trace_calls; }

}
