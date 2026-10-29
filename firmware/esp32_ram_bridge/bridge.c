/* RAM-only fixed UART2 bridge; no libc, flash mapping, IRQ or radio driver. */
#include <stdint.h>
#include <stddef.h>

#define U0 0x3ff40000u
#define U2 0x3ff6e000u
#define U0_TX 0x60000000u
#define U2_TX 0x6002e000u
#define GPIO_EN 0x3ff44020u
#define TX19 (1u << 19)
#define RX18 (1u << 18)
#define RESET13 (1u << 13)
#define GPIO_OUT 0x3ff44004u
#define GPIO_OUT_SET 0x3ff44008u
#define GPIO_OUT_CLEAR 0x3ff4400cu
#define GPIO_EN_SET 0x3ff44024u
#define GPIO_EN_CLEAR 0x3ff44028u
#define POLLS 1000u
#define HOST_POLLS 2000u
extern void ets_delay_us(uint32_t us);

static inline uint32_t read32(uint32_t address) {
    __asm__ volatile("memw" ::: "memory");
    uint32_t value = *(volatile uint32_t *)(uintptr_t)address;
    __asm__ volatile("memw" ::: "memory");
    return value;
}
static inline void store32(uint32_t address, uint32_t value) {
    __asm__ volatile("memw" ::: "memory");
    *(volatile uint32_t *)(uintptr_t)address = value;
    __asm__ volatile("memw" ::: "memory");
}
static void masked(uint32_t address, uint32_t mask, uint32_t value) {
    store32(address, (read32(address) & ~mask) | (value & mask));
}
static int change(uint32_t address, uint32_t mask, uint32_t value) {
    masked(address, mask, value);
    return (read32(address) & mask) == (value & mask);
}
struct saved { uint32_t address, mask, value; };
static struct saved saved[] = {
    {0x3ff000c0u, 1u << 23, 0}, {0x3ff000c4u, 1u << 23, 0},
    {GPIO_EN, RX18 | TX19, 0}, {U2 + 0x0cu, 0x7ffffu, 0},
    {U2 + 0x20u, 0x0849c13eu, 0}, {U2 + 0x24u, 1u << 23, 0},
    {U2 + 0x14u, 0xffffffu, 0}, {0x3ff49070u, 0x7200u, 0},
    {0x3ff44448u, 0xffu, 0}, {0x3ff4457cu, 0xfffu, 0},
    {0x3ff49074u, 0x7000u, 0}
};
static const uint8_t query_bytes[] = {0x55,0,1,1,1,0,2,0xa6,1,2,0xd2,0x41};
static const uint8_t trace_enable[] = {0x55,0,1,1,2,0,4,0xa3,9,1,0,1,0x23,0x43};
static const uint8_t trace_diagnostic[] = {0x55,0,1,2,2,0,4,0xa2,1,0x56,0,0,0x78,3};
static const uint8_t density_query[] = {0x55,0,1,3,1,0,2,0xa4,3,2,0x51,0x21};
static const uint8_t trace_restore[] = {0x55,0,1,4,2,0,4,0xa0,9,1,0,2,0x18,0x12};
static uint8_t captured[1024];
static uint8_t write_buffer[1029];
static uint32_t write_failed;
static uint32_t saved_valid, configured, query_used, exited;
static uint32_t boot_used, boot_touched, boot_mux, boot_matrix, boot_latch, boot_oe;

static int putch(uint8_t value) {
    for (uint32_t i = 0; i < HOST_POLLS; ++i) {
        if (((read32(U0 + 0x1cu) >> 16) & 255u) < 126u) {
            store32(U0_TX, value); /* direct store: NEVER read AHB FIFO */
            return 1;
        }
        ets_delay_us(1000);
    }
    return 0;
}
static void text(const char *s) { while (*s) { if (!putch((uint8_t)*s++)) return; } }
static void hex(uint32_t value, unsigned digits) {
    static const char alphabet[] = "0123456789abcdef";
    for (unsigned i = digits; i; --i) (void)putch((uint8_t)alphabet[(value >> ((i - 1) * 4)) & 15u]);
}
static int pop_rx(uint32_t base, uint8_t *result) {
    uint32_t status = read32(base + 0x1cu);
    uint32_t pointers = read32(base + 0x60u);
    if (!(status & 255u) || ((pointers >> 2) & 0x7ffu) == ((pointers >> 13) & 0x7ffu)) return 0;
    *result = (uint8_t)read32(base); /* APB only, never consume an empty FIFO */
    return 1;
}
static int tx_idle(int high) {
    for (uint32_t i = 0; i < POLLS; ++i) {
        uint32_t status = read32(U2 + 0x1cu);
        if (!(status & 0x0fff0000u)) return !high || (status >> 31);
        ets_delay_us(1000);
    }
    return 0;
}
static int restore_boot(void) {
    if (!boot_touched) return 1; /* Q/R/X without B never write GPIO13. */
    store32(GPIO_EN_CLEAR, RESET13); /* OE off BEFORE possibly restoring LOW latch. */
    int ok = !(read32(GPIO_EN) & RESET13);
    if (!ok) return 0; /* Never restore an old LOW latch while still driving. */
    ok &= change(0x3ff49038u, 0x7000u, boot_mux);
    ok &= change(0x3ff44564u, 0xfffu, boot_matrix);
    store32(boot_latch ? GPIO_OUT_SET : GPIO_OUT_CLEAR, RESET13);
    ok &= (read32(GPIO_OUT) & RESET13) == boot_latch;
    /* The original OE was required off; no re-enable/pulse on restoration. */
    ok &= !boot_oe && !(read32(GPIO_EN) & RESET13);
    boot_touched = 0;
    return ok;
}
static int restore(void) {
    int ok = restore_boot();
    ok &= change(GPIO_EN, TX19, 0);
    if (saved_valid) {
        for (unsigned i = sizeof(saved)/sizeof(saved[0]); i; --i) {
            struct saved *r = &saved[i - 1];
            if (!change(r->address, r->mask, r->value)) ok = 0;
        }
    }
    configured = 0;
    return ok;
}
static uint32_t source_from_host_div(uint32_t q0) {
    uint32_t integer = q0 & 0xfffffu;
    if (integer < 20u || integer > 1000u || (q0 & 0xff000000u)) return 0;
    uint32_t host_baud = integer < 100u ? 921600u : 115200u;
    uint32_t estimated = integer * host_baud + ((q0 >> 20) & 15u) * (host_baud / 16u);
    uint32_t source = 0;
    if (estimated >= 25480000u && estimated <= 26520000u) source = 26000000u;
    if (estimated >= 39200000u && estimated <= 40800000u) {
        if (source) return 0;
        source = 40000000u;
    }
    return source;
}
static int init(void) {
    uint32_t source = source_from_host_div(read32(U0 + 0x14u));
    if (!source) return 0;
    if (!(read32(0x3ff000c0u) & (1u << 23)) || (read32(0x3ff000c4u) & (1u << 23))) return 0;
    if (read32(GPIO_EN) & TX19) return 0;
    if (read32(0x3ff440d4u) & 4u) return 0;
    if ((read32(U2 + 0x18u) | read32(U2 + 0x44u)) & 1u) return 0;
    if (read32(U2 + 0x20u) & (3u << 17)) return 0;
    uint32_t mem = read32(U2 + 0x58u);
    if ((mem & 1u) || ((mem >> 3) & 15u) != 1u || ((mem >> 7) & 15u) != 1u) return 0;
    uint32_t status = read32(U2 + 0x1cu), pointers = read32(U2 + 0x60u);
    if ((status & 0x0fff00ffu) || ((pointers >> 2) & 0x7ffu) != ((pointers >> 13) & 0x7ffu)) return 0;
    for (unsigned i = 0; i < sizeof(saved)/sizeof(saved[0]); ++i) saved[i].value = read32(saved[i].address) & saved[i].mask;
    saved_valid = 1;
    uint32_t q = (source * 16u) / 921600u;
    int ok = change(GPIO_EN, RX18 | TX19, 0);
    ok &= change(U2 + 0x0cu, 0x7ffffu, 0);
    ok &= change(U2 + 0x20u, 0x0849c13eu, 0x0800001cu);
    ok &= change(U2 + 0x24u, 1u << 23, 0);
    ok &= change(U2 + 0x14u, 0xffffffu, (q >> 4) | ((q & 15u) << 20));
    ok &= change(0x3ff49070u, 0x7200u, 0x2200u);
    ok &= change(0x3ff44448u, 0xffu, 0x92u);
    configured = !!ok;
    if (!ok) (void)restore();
    return ok;
}
static int send_frame(const uint8_t *frame, unsigned length) {
    if (length > 14u) return 0;
    if (!tx_idle(1)) return 0;
    int ok = change(0x3ff4457cu, 0xfffu, 0x4c6u);
    ok &= change(0x3ff49074u, 0x7000u, 0x2000u);
    if (ok) ok = change(GPIO_EN, TX19, TX19);
    if (ok) {
        /* FIFO was empty; every fixed frame fits its128-byte allocation. */
        for (unsigned i = 0; i < length; ++i) store32(U2_TX, frame[i]);
        ok = tx_idle(1);
    }
    if (!change(GPIO_EN, TX19, 0)) ok = 0;
    return ok;
}
/* W is intentionally raw UART TX: it can carry radar flash-writing commands.
 * A shared empty-poll budget bounds receipt of the complete host packet. */
static int host_byte(uint8_t *value, unsigned *remaining) {
    while (*remaining) {
        if (pop_rx(U0, value)) return 1;
        --*remaining;
        ets_delay_us(1000);
    }
    return 0;
}
static int raw_write(void) {
    uint8_t lo, hi;
    unsigned remaining = HOST_POLLS;
    if (!configured || write_failed || exited) return 0;
    /* Latch failure before reading: truncated/oversized input must never be
     * reinterpreted as another mutating command. Only X is accepted afterward. */
    write_failed = 1;
    if (!host_byte(&lo, &remaining) || !host_byte(&hi, &remaining)) return 0;
    unsigned length = (unsigned)lo | ((unsigned)hi << 8);
    if (!length || length > sizeof(write_buffer)) return 0;
    for (unsigned i = 0; i < length; ++i)
        if (!host_byte(&write_buffer[i], &remaining)) return 0;
    if (!tx_idle(1)) return 0;
    int ok = change(0x3ff4457cu, 0xfffu, 0x4c6u);
    ok &= change(0x3ff49074u, 0x7000u, 0x2000u);
    if (ok) ok = change(GPIO_EN, TX19, TX19);
    remaining = HOST_POLLS;
    if (ok) {
        for (unsigned i = 0; i < length; ++i) {
            while (((read32(U2 + 0x1cu) >> 16) & 255u) >= 126u) {
                if (!remaining) { ok = 0; break; }
                --remaining;
                ets_delay_us(1000);
            }
            if (!ok) break;
            store32(U2_TX, write_buffer[i]); /* exactly once; never auto-resend */
        }
        if (ok) ok = tx_idle(1);
    }
    if (!change(GPIO_EN, TX19, 0)) ok = 0;
    if (ok) write_failed = 0;
    return ok;
}
static int query(void) {
    if (!configured || query_used) return 0;
    query_used = 1;
    return send_frame(query_bytes, sizeof(query_bytes));
}
static int reset_preflight(void) {
    /* GPIO13 is RTCIO14 / TOUCH_PAD4, source-bound to IDF5.5.5. Read only. */
    uint32_t rtc_pad = read32(0x3ff484a4u);
    if (rtc_pad & ((1u << 19) | (1u << 31))) return 0; /* RTC ownership or pad hold */
    if (read32(0x3ff480c8u) & (1u << 12)) return 0; /* pad4 forced hold */
    if (read32(0x3ff440bcu) & 4u) return 0; /* unsupported open-drain mode */
    boot_oe = read32(GPIO_EN) & RESET13;
    if (boot_oe) return 0;
    boot_latch = read32(GPIO_OUT) & RESET13;
    boot_matrix = read32(0x3ff44564u) & 0xfffu;
    boot_mux = read32(0x3ff49038u) & 0x7000u;
    return 1; /* no GPIO13 change: T must pass this BEFORE trace enable */
}
static int reset_pulse(void) {
    boot_touched = 1;
    store32(GPIO_OUT_SET, RESET13); /* stage released HIGH before mux or OE */
    if (!(read32(GPIO_OUT) & RESET13)) return 0;
    int ok = change(0x3ff44564u, 0xfffu, 0x500u); /* GPIO256, GPIO-controlled OE */
    ok &= change(0x3ff49038u, 0x7000u, 0x2000u);
    if (!ok) return 0;
    store32(GPIO_EN_SET, RESET13);
    if (!(read32(GPIO_EN) & RESET13) || !(read32(GPIO_OUT) & RESET13)) {
        store32(GPIO_EN_CLEAR, RESET13);
        return 0;
    }
    store32(GPIO_OUT_CLEAR, RESET13); /* one stock-polarity LOW pulse */
    int low_ok = !(read32(GPIO_OUT) & RESET13);
    ets_delay_us(10000);
    store32(GPIO_OUT_SET, RESET13); /* always release before capture/reply */
    int high_ok = !!(read32(GPIO_OUT) & RESET13);
    if (!high_ok) store32(GPIO_EN_CLEAR, RESET13);
    return low_ok && high_ok;
}
static int boot_reset(void) {
    if (!configured || boot_used || query_used) return 0;
    boot_used = 1;
    query_used = 1; /* B/Q/T are mutually exclusive in one RAM session. */
    if (!reset_preflight()) return 0;
    return reset_pulse();
}
static unsigned collect(unsigned limit, unsigned max_polls, unsigned length) {
    for (unsigned polls = 0; polls < max_polls && length < limit; ++polls) {
        uint8_t value;
        while (length < limit && pop_rx(U2, &value)) captured[length++] = value;
        if (length < limit) ets_delay_us(1000);
    }
    return length;
}
static unsigned collect_reply(void) {
    unsigned length=0, idle=0;
    for (unsigned polls=0;polls<100u && length<256u;++polls) {
        unsigned before=length;
        uint8_t value;
        while (length<256u && pop_rx(U2,&value)) captured[length++]=value;
        idle=(length && before==length)?idle+1u:0u;
        if (idle>=2u || length==256u) break;
        ets_delay_us(1000);
    }
    return length;
}
static void report_capture(const char *label, unsigned length, uint32_t raw) {
    text(label); hex(length, 4); text(" "); hex(raw, 8); text(" ");
    for (unsigned i = 0; i < length; ++i) hex(captured[i], 2);
    text("\n");
}
static void capture(unsigned limit, unsigned max_polls, const char *label) {
    unsigned length = collect(limit, max_polls, 0);
    report_capture(label, length, read32(U2 + 4u));
}
static int trace_diag(void) {
    if (!configured || boot_used || query_used) return 0;
    boot_used = 1;
    query_used = 1;
    if (!reset_preflight()) return 0; /* no trace/pin change if cleanup unavailable */
    (void)send_frame(trace_enable, sizeof(trace_enable));
    unsigned length = collect(896, 100, 0); /* brief immediate RX service */
    (void)send_frame(trace_diagnostic, sizeof(trace_diagnostic));
    length = collect(896, 500, length); /* reserve128 bytes for restore ACK/text */
    (void)send_frame(density_query, sizeof(density_query)); /* fixed JEDEC byte2 getter */
    length = collect(896, 100, length);
    (void)send_frame(trace_restore, sizeof(trace_restore)); /* ALWAYS attempted */
    length = collect(1024, 250, length);
    uint32_t raw = read32(U2 + 4u); /* freeze TRACE bytes/flags BEFORE reset */
    int reset_ok = reset_pulse(); /* exactly one guarded pulse, no capture after */
    report_capture("TRACE ", length, raw);
    text(reset_ok ? "RESETOK\n" : "ERR RESET\n");
    return 1;
}
void bridge_main(void) {
    if (!init()) { text("ERR INIT\n"); for (;;) ets_delay_us(1000); }
    text("FP2RAM1\n");
    for (;;) {
        uint8_t command;
        if (exited) { ets_delay_us(1000); continue; }
        if (!pop_rx(U0, &command)) { ets_delay_us(1000); continue; }
        if (write_failed && command != 'X') { text("ERR WRITE\n"); continue; }
        if (command == 'W') text(raw_write() ? "WOK\n" : "ERR WRITE\n");
        else if (command == 'P') {
            unsigned length=collect_reply();
            report_capture("RX ",length,read32(U2+4u));
        }
        else if (command == 'Q') {
            if (query_used) text("ERR CMD\n");
            else text(query() ? "QUERYOK\n" : "ERR QUERY\n");
        } else if (command == 'R') capture(256, POLLS, "RX ");
        else if (command == 'B') {
            if (boot_reset()) capture(1024, 5000, "BOOT ");
            else text("ERR BOOT\n");
        }
        else if (command == 'T') { if (!trace_diag()) text("ERR TRACE\n"); }
        else if (command == 'X') { text(restore() ? "BYE\n" : "ERR RESTORE\n"); exited = 1; }
        else text("ERR CMD\n");
    }
}
