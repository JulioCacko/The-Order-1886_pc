// SPDX-License-Identifier: GPL-2.0-or-later
// helper thread sizing. Counts follow the hardware threads this process may run on
// (the affinity mask, so `taskset` can emulate a Steam Deck), and speculative helpers run as
// SCHED_IDLE: they use cores the game leaves idle and never take time from its threads.

#pragma once

#include <algorithm>
#include <thread>
#ifdef _WIN32
#include <bit>
#include <windows.h>
#else
#include <sched.h>
#include <sys/resource.h>
#include <time.h>
#include <unistd.h>
#endif

namespace Ps4Threads {
#ifdef _WIN32
/// Hardware threads available to the process (its affinity mask).
inline unsigned Available() {
    DWORD_PTR process = 0, system = 0;
    if (GetProcessAffinityMask(GetCurrentProcess(), &process, &system) && process) {
        return std::max(1, std::popcount(static_cast<unsigned long long>(process)));
    }
    return std::max(1u, std::thread::hardware_concurrency());
}

/// The calling thread only runs when cores are otherwise idle (lowest Windows priority).
inline void MakeBackground() {
    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_IDLE);
}
#else

/// Hardware threads available to the process.
inline unsigned Available() {
    cpu_set_t set;
    CPU_ZERO(&set);
    if (sched_getaffinity(0, sizeof(set), &set) == 0) {
        return std::max(1, CPU_COUNT(&set));
    }
    return std::max(1u, std::thread::hardware_concurrency());
}

/// The calling thread only runs on otherwise idle cores (falls back to the lowest nice level).
inline void MakeBackground() {
    sched_param param{};
    if (sched_setscheduler(0, SCHED_IDLE, &param) != 0) {
        setpriority(PRIO_PROCESS, static_cast<id_t>(gettid()), 19);
    }
}
#endif

/// One failed poll of a condition another thread sets (#134). Short waits stay a spin; a long
/// one gives up the core, then sleeps 100 µs per poll, instead of a std::this_thread::yield()
/// loop that keeps a core busy (on 6 threads it took them from the guest's job threads).
/// Start `spins` at 0 for each wait, and again whenever the waiter made progress.
inline void Backoff(unsigned& spins) {
    constexpr unsigned PauseSpins = 64, YieldSpins = 256;
    if (spins < PauseSpins) {
        ++spins;
        __builtin_ia32_pause();
        return;
    }
    if (spins < PauseSpins + YieldSpins) {
        ++spins;
#ifdef _WIN32
        SwitchToThread(); // any ready thread; Sleep(0) (std::this_thread::yield) only equal priority
#else
        sched_yield();
#endif
        return;
    }
#ifdef _WIN32
    // A plain Sleep() waits for the system timer (1 to 15.6 ms); this timer keeps 100 µs.
    static thread_local HANDLE timer = CreateWaitableTimerExW(
        nullptr, nullptr, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_ALL_ACCESS);
    LARGE_INTEGER due;
    due.QuadPart = -1000; // relative, 100 ns units
    if (timer && SetWaitableTimer(timer, &due, 0, nullptr, nullptr, FALSE)) {
        WaitForSingleObject(timer, INFINITE);
    } else {
        SwitchToThread();
    }
#else
    const timespec due{0, 100000};
    nanosleep(&due, nullptr);
#endif
}

} // namespace Ps4Threads
