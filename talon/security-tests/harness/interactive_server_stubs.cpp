// Test harness for webserver/core/interactive_server.cpp.
//
// Links the real interactive server against stubs for the rest of the
// runtime so the command parser can be driven over a loopback socket on an
// ephemeral port from pytest. Every stubbed protocol entry point prints a
// "STUB <name>" line to stdout so the test can assert on which side effects
// the server actually performed.
//
// Usage: interactive_server_harness <port>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <time.h>

#include "ladder.h"
#include "oplc_snap7.h"

uint8_t run_openplc = 1;
unsigned char log_buffer[1000000];
int log_index = 0;

extern "C" void openplc_log(char *logmsg)
{
    int msg_len = strlen(logmsg);
    if (log_index + msg_len >= (int)sizeof(log_buffer) - 1)
    {
        log_index = 0;
    }
    memcpy(&log_buffer[log_index], logmsg, msg_len);
    log_index += msg_len;
    log_buffer[log_index] = '\0';
    printf("LOG %s", logmsg);
    fflush(stdout);
}

void sleepms(int milliseconds)
{
    struct timespec ts;
    ts.tv_sec = milliseconds / 1000;
    ts.tv_nsec = (milliseconds % 1000) * 1000000;
    nanosleep(&ts, NULL);
}

void closeSocket(int fd)
{
    close(fd);
}

bool SetSocketBlockingEnabled(int fd, bool blocking)
{
    int flags = fcntl(fd, F_GETFL, 0);
    if (flags < 0) return false;
    flags = blocking ? (flags & ~O_NONBLOCK) : (flags | O_NONBLOCK);
    return fcntl(fd, F_SETFL, flags) == 0;
}

void startServer(uint16_t port, int protocol_type)
{
    printf("STUB startServer port=%d protocol=%d\n", port, protocol_type);
    fflush(stdout);
    if (protocol_type == MODBUS_PROTOCOL)
    {
        while (run_modbus) sleepms(10);
    }
    else if (protocol_type == ENIP_PROTOCOL)
    {
        while (run_enip) sleepms(10);
    }
}

void dnp3StartServer(int port)
{
    printf("STUB dnp3StartServer port=%d\n", port);
    fflush(stdout);
    while (run_dnp3) sleepms(10);
}

void startPstorage()
{
    printf("STUB startPstorage\n");
    fflush(stdout);
    while (run_pstorage) sleepms(10);
}

void initializeSnap7() {}
void finalizeSnap7() {}
void startSnap7()
{
    printf("STUB startSnap7\n");
    fflush(stdout);
}
void stopSnap7()
{
    printf("STUB stopSnap7\n");
    fflush(stdout);
}

int main(int argc, char **argv)
{
    if (argc < 2)
    {
        fprintf(stderr, "usage: %s <port>\n", argv[0]);
        return 2;
    }
    time(&start_time);
    startInteractiveServer(atoi(argv[1]));
    printf("HARNESS exit\n");
    fflush(stdout);
    return 0;
}
