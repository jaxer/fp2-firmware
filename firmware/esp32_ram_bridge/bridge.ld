ENTRY(_start)
MEMORY {
    iram (rx) : ORIGIN = 0x40090000, LENGTH = 0x2000
    dram (rw) : ORIGIN = 0x3ffb0000, LENGTH = 0x2000
}
SECTIONS {
    .entry : ALIGN(4) { KEEP(*(.entry)) } > iram
    .text : ALIGN(4) { *(.literal .literal.*) *(.text .text.*) } > iram
    .data : ALIGN(4) { *(.rodata .rodata.*) *(.data .data.*) } > dram
    .bss (NOLOAD) : ALIGN(16) {
        __bss_start = ABSOLUTE(.);
        *(.bss .bss.* COMMON)
        . = ALIGN(16);
        __bss_end = ABSOLUTE(.);
    } > dram
    .stack (NOLOAD) : ALIGN(16) {
        _stack_bottom = ABSOLUTE(.);
        . += 4096;
        _stack_top = ABSOLUTE(.);
    } > dram
    /DISCARD/ : { *(.comment .note* .eh_frame* .xtensa.info) }
    ASSERT(_start == 0x40090000, "entry must be fixed IRAM address")
    ASSERT(_stack_top <= 0x3ffb2000, "own data+BSS+stack must fit8KiB")
}
PROVIDE(ets_delay_us = 0x40008534);
