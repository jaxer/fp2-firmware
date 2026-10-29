ENTRY(export_init)
MEMORY {
 HOOK (rx) : ORIGIN = 0xffe4, LENGTH = 4
 TCMA (rx) : ORIGIN = 0x38000, LENGTH = 0x1000
}
SECTIONS {
 .hook : { *(.hook) } > HOOK
 .text : { *(.text*) *(.rodata*) } > TCMA
 /DISCARD/ : { *(.ARM.attributes) *(.comment) *(.note*) }
 ASSERT(SIZEOF(.hook) == 4, "op1 patch must be exactly four bytes")
 ASSERT(SIZEOF(.text) <= 0x1000, "export exceeds reviewed placement window")
}
