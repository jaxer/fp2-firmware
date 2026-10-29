/* ESP32 ROM main invokes entry with CALLX8. This context never returns. */
.section .entry,"ax",@progbits
.global _start
.type _start,@function
.align 4
_start:
    entry a1, 32
    rsil a2, 15
    movi a2, 0
    wsr a2, WINDOWBASE
    rsync
    movi a2, 1
    wsr a2, WINDOWSTART
    rsync
    j .Linit
    .align 4
.Lstack: .word _stack_top
.Lbss_start: .word __bss_start
.Lbss_end: .word __bss_end
.Linit:
    l32r a1, .Lstack
    movi a2, 4
    slli a2, a2, 16
    addi a2, a2, 0x2f  /* PS.WOE, PS.UM, INTLEVEL15; CALLINC0 */
    wsr a2, PS
    rsync
    l32r a2, .Lbss_start
    l32r a3, .Lbss_end
    movi a4, 0
.Lzero:
    bgeu a2, a3, .Lmain
    s32i a4, a2, 0
    addi a2, a2, 4
    j .Lzero
.Lmain:
    call8 bridge_main
.Lidle:
    j .Lidle
.size _start, .-_start
