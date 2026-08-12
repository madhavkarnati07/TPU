import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge


CMD_LOAD_X = 0x10
CMD_LOAD_WQ = 0x11
CMD_LOAD_WK = 0x12
CMD_LOAD_WV = 0x13
CMD_RUN_ATTENTION = 0x20
CMD_READ_RESULT = 0x30
CMD_READ_DEBUG = 0x31
CMD_FLUSH = 0xFF


async def wait_status_bit(dut, bit, timeout=1000):
    for _ in range(timeout):
        await FallingEdge(dut.clk)
        if (int(dut.uio_out.value) >> bit) & 1:
            return
    raise AssertionError(f"timed out waiting for uio_out[{bit}]")


async def send_byte(dut, value):
    await wait_status_bit(dut, 4)
    dut.ui_in.value = value
    dut.uio_in.value = int(dut.uio_in.value) | 0x01
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.uio_in.value = int(dut.uio_in.value) & ~0x01


async def receive_byte(dut):
    await wait_status_bit(dut, 5)
    value = int(dut.uo_out.value)
    dut.uio_in.value = int(dut.uio_in.value) | 0x02
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.uio_in.value = int(dut.uio_in.value) & ~0x02
    return value


async def load(dut, command, payload):
    await send_byte(dut, command)
    for value in payload:
        await send_byte(dut, value)


async def reset(dut):
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await FallingEdge(dut.clk)


async def read_status(dut):
    await send_byte(dut, CMD_READ_DEBUG)
    await send_byte(dut, 0x00)
    return await receive_byte(dut)


@cocotb.test()
async def test_reference_attention_transaction(dut):
    cocotb.start_soon(Clock(dut.clk, 100, unit="ns").start())
    await reset(dut)

    assert int(dut.uio_oe.value) == 0xF0

    await load(dut, CMD_LOAD_X, [0x10, 0x01, 0x11, 0xF1])
    await load(dut, CMD_LOAD_WQ, [0x10, 0x01])
    await load(dut, CMD_LOAD_WK, [0x10, 0x01])
    await load(dut, CMD_LOAD_WV, [0x10, 0x02])
    await send_byte(dut, CMD_RUN_ATTENTION)
    await wait_status_bit(dut, 7)

    await send_byte(dut, CMD_READ_RESULT)
    result = [await receive_byte(dut) for _ in range(4)]
    assert result == [0x01, 0x02, 0x01, 0x02]


@cocotb.test()
async def test_protocol_guards_and_flush(dut):
    cocotb.start_soon(Clock(dut.clk, 100, unit="ns").start())
    await reset(dut)

    await send_byte(dut, CMD_READ_DEBUG)
    await send_byte(dut, 0x01)
    status = await read_status(dut)
    assert status == 0x04

    await send_byte(dut, CMD_FLUSH)
    assert await read_status(dut) == 0x00

    await send_byte(dut, CMD_RUN_ATTENTION)
    assert await read_status(dut) == 0x04

    await send_byte(dut, CMD_FLUSH)
    await send_byte(dut, CMD_READ_RESULT)
    assert await read_status(dut) == 0x04
