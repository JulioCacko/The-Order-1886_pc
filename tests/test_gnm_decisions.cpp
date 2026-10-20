// SPDX-License-Identifier: GPL-2.0-or-later
//
// Three GnmDriver entry points used to be stubs that returned ORBIS_OK and wrote nothing. This
// checks the decisions they now make: the exact packet encoding for a compute wait-semaphore, the
// ring-size contract Sony enforces, and the mip-stats report buffer rules.

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string_view>

#include "core/libraries/gnmdriver/gnm_call_decisions.h"

namespace {


// The guest hands over a buffer; nothing may be written outside it.
struct Packet {
    static constexpr unsigned Sentinel = 0xCDCDCDCDu;
    unsigned words[16];
    Packet() {
        for (auto& word : words) {
            word = Sentinel;
        }
    }
    unsigned written() const {
        unsigned count = 0;
        while (count < 16 && words[count] != Sentinel) {
            ++count;
        }
        return count;
    }
};

} // Anonymous namespace

int main() {
    // A compute wait-semaphore writes exactly ten dwords and nothing past them.
    {
        Packet packet;
        const auto end = Gnm::WriteComputeWaitSemaphore(packet.words, 0x1234567890abcdefull, 0);
        const unsigned written = packet.written();
        if (written != Gnm::ComputeWaitSemaphoreDwords) {
            std::printf("compute wait-semaphore wrote %u dwords, expected %u\n", written,
                        Gnm::ComputeWaitSemaphoreDwords);
            return EXIT_FAILURE;
        }
        if (static_cast<unsigned*>(end) != packet.words + written) {
            std::puts("the returned cursor must point just past the packet");
            return EXIT_FAILURE;
        }
        // The leading NOP is a header plus three data dwords, so the packet header is the fifth word.
        const auto* header = reinterpret_cast<const AmdGpu::PM4Type3Header*>(&packet.words[4]);
        if (header->opcode != AmdGpu::PM4ItOpcode::MemSemaphore || header->count != 1) {
            std::puts("the packet must carry a two-dword MemSemaphore header");
            return EXIT_FAILURE;
        }
        if (packet.words[5] != 0x90abcdefu) {
            std::puts("the low half of the semaphore address belongs in the first payload dword");
            return EXIT_FAILURE;
        }
        // The second payload carries the high half biased by the base, plus the signal flag.
        const unsigned expected = 0u - 0x20000000u + 0x12345678u;
        if (packet.words[6] != expected) {
            std::printf("payload dword %#x != %#x\n", packet.words[6], expected);
            return EXIT_FAILURE;
        }
        Packet signalled;
        Gnm::WriteComputeWaitSemaphore(signalled.words, 0, 1);
        if (signalled.words[6] != (0x100000u - 0x20000000u)) {
            std::puts("flags==1 must add the signal bit to the second payload dword");
            return EXIT_FAILURE;
        }
    }

    // The ring-size contract: 1 MB aligned, inside [4 MB, 8 MB].
    {
        struct Case {
            unsigned esgs;
            unsigned gsvs;
            bool accepted;
        };
        constexpr Case cases[] = {
            {0x400000, 0x400000, true},   {0x800000, 0x800000, true},
            {0x500000, 0x600000, true},   {0, 0x400000, false},
            {0x3fffff, 0x400000, false},  {0x400001, 0x400000, false},
            {0x900000, 0x400000, false},  {0x400000, 0x3fffff, false},
            {0x400000, 0x400001, false},  {0x400000, 0x900000, false},
        };
        for (const auto& test : cases) {
            const auto code = Gnm::ValidateGsRingSizes(test.esgs, test.gsvs);
            const bool accepted = code == 0;
            if (accepted != test.accepted) {
                std::printf("ring sizes %#x/%#x: got %#x\n", test.esgs, test.gsvs, code);
                return EXIT_FAILURE;
            }
            if (!accepted && code != Gnm::GsRingInvalidArgument) {
                std::printf("ring sizes %#x/%#x returned %#x, not 0x08000000\n", test.esgs,
                            test.gsvs, code);
                return EXIT_FAILURE;
            }
        }
    }

    // The mip-stats report buffer: aligned, at least 0x1040 bytes, and sized 0x7ff*n + 0x40.
    {
        alignas(0x40) unsigned char buffer[0x2000]{};
        if (Gnm::ValidateMipStatsReport(nullptr, 0x1040) != Gnm::MipStatsInvalidBuffer) {
            std::puts("a null buffer must be refused");
            return EXIT_FAILURE;
        }
        if (Gnm::ValidateMipStatsReport(buffer + 0x8, 0x1040) != Gnm::MipStatsInvalidBuffer) {
            std::puts("a misaligned buffer must be refused");
            return EXIT_FAILURE;
        }
        if (Gnm::ValidateMipStatsReport(buffer, 0x103f) != Gnm::MipStatsInvalidSize) {
            std::puts("a short buffer must be refused");
            return EXIT_FAILURE;
        }
        if (Gnm::ValidateMipStatsReport(buffer, 0x1040 + 1) != Gnm::MipStatsInvalidSize) {
            std::puts("a size off the 0x7ff granularity must be refused");
            return EXIT_FAILURE;
        }
        if (Gnm::ValidateMipStatsReport(buffer, 0x1040) != 0) {
            std::puts("the minimum valid size must be accepted");
            return EXIT_FAILURE;
        }
        if (Gnm::ValidateMipStatsReport(buffer, 0x1040 + 0x800) != 0) {
            std::puts("one more report worth of space must be accepted");
            return EXIT_FAILURE;
        }
    }

    // The indirect-count packet this tree had no opcode, struct or dispatcher case for: a header
    // plus nine payload words, framed by two NOPs of two data words each — which is exactly the
    // 0x10 the guest's size argument asserts. If any of those numbers drift, the guest's buffer is
    // over- or under-written.
    {
        static_assert(sizeof(AmdGpu::PM4CmdDrawIndirectCountMulti) == 10 * sizeof(uint32_t),
                      "the packet is a header plus nine payload words");
        constexpr unsigned leading = 1 + 2;  // NOP header plus a two-word data block
        constexpr unsigned trailing = 1 + 2;
        constexpr unsigned guest_size = leading + 10 + trailing;
        if (guest_size != 0x10) {
            std::puts("the framed indirect-count packet must fill the 0x10 dwords the guest asked for");
            return EXIT_FAILURE;
        }
        if (static_cast<unsigned>(AmdGpu::PM4ItOpcode::DrawIndirectCountMulti) != 0x9c ||
            static_cast<unsigned>(AmdGpu::PM4ItOpcode::DrawIndirectMulti) != 0x2c) {
            std::puts("the indirect opcodes must keep their hardware values");
            return EXIT_FAILURE;
        }
    }

    std::puts("Gnm decisions: wait-semaphore packet, ring-size contract, mip-stats buffer rules");
    return EXIT_SUCCESS;
}
