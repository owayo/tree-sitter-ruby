// 計測専用のコピーへ挿入する。通常のライブラリには組み込まない。
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef struct { long long QuadPart; } ProfileCounter;
__declspec(dllimport) int __stdcall QueryPerformanceCounter(ProfileCounter *value);
__declspec(dllimport) int __stdcall QueryPerformanceFrequency(ProfileCounter *value);

static unsigned profile_phase = 3;
static uint64_t profile_calls[4], profile_ticks[4], profile_allocs[4], profile_frees[4];

static uint64_t profile_clock(void) {
    ProfileCounter value;
    QueryPerformanceCounter(&value);
    return (uint64_t)value.QuadPart;
}

static void profile_report(void) {
    ProfileCounter frequency;
    QueryPerformanceFrequency(&frequency);
    fprintf(stderr, "{\"qpc_hz\":%lld,\"phases\":[", frequency.QuadPart);
    for (unsigned i = 0; i < 4; i++) {
        fprintf(stderr, "%s{\"phase\":%u,\"calls\":%llu,\"ticks\":%llu,\"allocations\":%llu,\"frees\":%llu}",
            i ? "," : "", i, profile_calls[i], profile_ticks[i], profile_allocs[i], profile_frees[i]);
    }
    fprintf(stderr, "]}\n");
}

static void *profile_calloc(size_t count, size_t size) {
    static int registered = 0;
    if (!registered) { atexit(profile_report); registered = 1; }
    profile_allocs[profile_phase]++;
    return calloc(count, size);
}

static void *profile_realloc(void *pointer, size_t size) {
    profile_allocs[profile_phase]++;
    return realloc(pointer, size);
}

static void profile_free(void *pointer) {
    if (pointer) profile_frees[profile_phase]++;
    free(pointer);
}

static void *profile_malloc(size_t size) {
    profile_allocs[profile_phase]++;
    return malloc(size);
}

#define ts_calloc profile_calloc
#define ts_malloc profile_malloc
#define ts_realloc profile_realloc
#define ts_free profile_free
