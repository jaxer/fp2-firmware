.syntax unified
.cpu cortex-r4
.thumb
.section .hook,"ax",%progbits
.global export_entry_patch
.thumb_func
export_entry_patch:
    b.w export_handler
.section .text,"ax",%progbits
.global export_init, export_handler, export_code_end, export_scratch, export_blob_end
.type export_init,%function
.thumb_func
export_init:
    /* Compatibility symbol only: packaging leaves original cinit hook intact. */
    ldr pc, =0x24291
.size export_init, .-export_init

/* 192 bytes: saved r3-r7/LR24 + locals168. Body0..135, status136,
 * packed descriptor138/140, original r0/r1 144/148, CPSR152.
 * DataSP+8 aligned8. r4=mode,r5=address,r6=count,r7=len/controller. */
.type export_handler,%function
.thumb_func
export_handler:
    push {r3-r7,lr}
    sub sp, sp, #168
    str r0, [sp,#144]
    str r1, [sp,#148]
    mov r7, r2
    cmp r2, #6
    blo fallback
    ldrb r3, [r1]
    cmp r3, #1
    bne fallback
    ldrb r3, [r1,#1]
    cmp r3, #2
    bne fallback
    ldrb r3, [r1,#2]
    cmp r3, #'F'
    bne fallback
    ldrb r3, [r1,#3]
    cmp r3, #'P'
    bne fallback
    ldrb r3, [r1,#4]
    cmp r3, #'2'
    bne fallback
    ldrb r4, [r1,#5]
    movs r5, #0
    movs r6, #0
    cmp r7, #12
    blo bad_format
    ldrb r3, [r1,#6]
    cmp r3, #1
    bne bad_format
    ldrb r5, [r1,#7]
    ldrb r3, [r1,#8]
    orr r5, r3, r5, lsl #8
    ldrb r3, [r1,#9]
    orr r5, r3, r5, lsl #8
    ldrb r3, [r1,#10]
    orr r5, r3, r5, lsl #8
    ldrb r6, [r1,#11]
    cmp r6, #1
    blo bad_format
    cmp r6, #128
    bhi bad_format
    cmp r4, #'W'
    beq validate_write_length
    cmp r7, #12
    bne bad_format
    bl zero_read_buffer
    cmp r4, #'M'
    beq memory_read
    cmp r4, #'S'
    beq check_sfdp_bounds
    cmp r4, #'R'
    beq unsupported_array
    cmp r4, #'J'
    bne bad_format
    cmp r5, #0
    bne bad_format
    cmp r6, #3
    bne bad_format
    b check_ready
validate_write_length:
    cmp r6, #32
    bhi bad_format
    add r3, r6, #12
    cmp r7, r3
    bne bad_format
    tst r5, #7
    bne bad_bounds
    tst r6, #7
    bne bad_bounds
    bl ram_range
    cmp r0, #0
    beq bad_bounds
    adds r2, r5, r6 /* already nonwrapping from RAM range validation */
    ldr r0, =export_scratch
    cmp r5, r0
    blo reject_monitor_overlap
    ldr r0, =export_blob_end
    cmp r2, r0
    bls check_stack_overlap
reject_monitor_overlap:
    ldr r0, =export_blob_end
    cmp r5, r0
    bhs check_stack_overlap
    ldr r0, =export_init
    bic r0, r0, #1
    cmp r2, r0
    bhi bad_bounds
check_stack_overlap:
    /* Never overwrite this live automatic frame, including saved registers. */
    add r0, sp, #192
    cmp r5, r0
    bhs prepare_write
    mov r0, sp
    cmp r2, r0
    bhi bad_bounds
prepare_write:
    bl zero_read_buffer
    ldr r1, [sp,#148]
    adds r1, r1, #12
    add r3, sp, #8
    mov r2, r6
copy_write_payload:
    ldrb r0, [r1],#1
    strb r0, [r3],#1
    subs r2, r2, #1
    bne copy_write_payload
    mrs r0, CPSR
    str r0, [sp,#152]
    cpsid i
    mov r7, r5
    add r3, sp, #8
    mov r2, r6
write_ram_loop:
    ldrd r0, r1, [r3],#8
    strd r0, r1, [r7],#8
    subs r2, r2, #8
    bne write_ram_loop
    dsb sy
    isb sy
    ldr r0, [sp,#152]
    msr CPSR_c, r0
    b success
memory_read:
    bl ram_range
    cmp r0, #0
    bne copy_memory
    ldr r0, =0xc0000000
    cmp r5, r0
    blo bad_bounds
    ldr r0, =0xc0800000 /*8MiB mappedflash; nextaddress is QSPI MMIO!*/
    subs r0, r0, r6
    cmp r5, r0
    bhi bad_bounds
    /* QSPI checks and direct copy share one IRQ-masked window. */
    mrs r0, CPSR
    str r0, [sp,#152]
    cpsid i
    ldr r3, =0x0802dd8c
    ldrb r0, [r3,#8]
    cmp r0, #1
    bne critical_not_ready
    ldr r0, [r3,#4]
    cmp r0, #0
    beq critical_not_ready
    ldr r0, [r0]
    cmp r0, #0
    beq critical_not_ready
    ldr r0, [r0,#16]
    ldr r1, =0xc0800000
    cmp r0, r1
    bne critical_bad_mapping
    ldr r1, [r0,#100] /*SPI_SWITCH MMPT_S; no read-to-clear STATUS access*/
    tst r1, #1
    beq critical_bad_mapping
    ldr r1, [r0,#84] /*SETUP0 lowbyte is readopcode*/
    uxtb r1, r1
    cmp r1, #3
    beq copy_memory_masked
    cmp r1, #0x0b
    beq copy_memory_masked
    cmp r1, #0x3b
    beq copy_memory_masked
    cmp r1, #0x6b
    beq copy_memory_masked
critical_bad_mapping:
    movs r2, #7
    b restore_error
critical_not_ready:
    movs r2, #2
restore_error:
    ldr r0, [sp,#152]
    msr CPSR_c, r0
    mov r0, r2
    b error_reply
copy_memory:
    mrs r0, CPSR
    str r0, [sp,#152]
    cpsid i
copy_memory_masked:
    mov r7, r5
    add r3, sp, #8
    mov r2, r6
read_memory_loop:
    ldrb r0, [r7],#1
    strb r0, [r3],#1
    subs r2, r2, #1
    bne read_memory_loop
    ldr r0, [sp,#152]
    msr CPSR_c, r0
    b success
check_sfdp_bounds:
    movw r3, #0x4000
    subs r3, r3, r6
    cmp r5, r3
    bhi bad_bounds
check_ready:
    ldr r3, =0x0802dd8c
    ldrb r0, [r3,#8]
    cmp r0, #1
    bne not_ready
    ldr r0, [r3,#4]
    cmp r0, #0
    beq not_ready
    ldr r7, [r0]
    cmp r7, #0
    beq not_ready
    cmp r4, #'J'
    beq read_jedec
    mov r0, r7
    mov r1, r5
    mov r2, r6
    add r3, sp, #8
    bl vendor_sfdp
    b success
read_jedec:
    mov r0, r7
    add r1, sp, #8
    bl vendor_jedec
success:
    movs r0, #0
    b reply
bad_format:
    movs r0, #1
    b error_reply
not_ready:
    movs r0, #2
    b error_reply
bad_bounds:
    movs r0, #4
    b error_reply
unsupported_array:
    movs r0, #6
error_reply:
    strb r0, [sp,#136]
    bl zero_read_buffer
    ldrb r0, [sp,#136]
    movs r6, #0
reply:
    strb r0, [sp,#2]
    movs r0, #3
    strb r0, [sp]
    strb r4, [sp,#1]
    lsrs r0, r5, #24
    strb r0, [sp,#3]
    lsrs r0, r5, #16
    strb r0, [sp,#4]
    lsrs r0, r5, #8
    strb r0, [sp,#5]
    strb r5, [sp,#6]
    strb r6, [sp,#7]
    adds r0, r6, #8
    strh r0, [sp,#138]
    mov r0, sp
    str r0, [sp,#140]
    movs r0, #4
    movw r1, #0x0102
    movs r2, #5
    add r3, sp, #138
    bl vendor_serialize
    add sp, sp, #168
    pop {r3-r7,pc}
fallback:
    mov r2, r7
    ldr r0, [sp,#144]
    ldr r1, [sp,#148]
    add sp, sp, #168
    pop {r3-r7,lr}
    ldr pc, =export_original_op1
.size export_handler, .-export_handler

/* Return r0=1 iff entire nonemptyr5/r6 range lies in allowedRAM. */
.thumb_func
ram_range:
    mov r0, #0x40000
    subs r0, r0, r6
    cmp r5, r0
    bls ram_ok
    ldr r0, =0x08000000
    cmp r5, r0
    blo ram_no
    ldr r0, =0x08030000 /*192KiB physicalTCMB, noextraallocatedbanks*/
    subs r0, r0, r6
    cmp r5, r0
    bhi ram_no
ram_ok:
    movs r0, #1
    bx lr
ram_no:
    movs r0, #0
    bx lr
.thumb_func
zero_read_buffer:
    add r3, sp, #8
    movs r0, #0
    movs r2, #32
zero_loop:
    str r0, [r3],#4
    subs r2, r2, #1
    bne zero_loop
    bx lr
.global export_original_op1
.type export_original_op1,%function
.thumb_func
export_original_op1:
    /* Replay EXACT displaced bytes08b50a78 from originalffe4..ffe8. */
    push {r3,lr}
    ldrb r2, [r1]
    b.w 0xffe8
.size export_original_op1, .-export_original_op1
.thumb_func
vendor_sfdp: ldr pc, =0x2376d
.thumb_func
vendor_jedec: ldr pc, =0x246b9
.thumb_func
vendor_serialize: ldr pc, =0x18fd9
.ltorg
.balign 8
export_code_end:
export_scratch:
    .space 32,0
export_blob_end:
