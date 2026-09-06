SIM ?= icarus
TOPLEVEL_LANG ?= verilog
PYTHON ?= python3
BENCHMARK_KIND ?= active

BENCHMARK_DIR := $(CURDIR)
ROOT := $(abspath $(BENCHMARK_DIR)/../..)
SRC_DIR := $(ROOT)/src
PROJECT_SOURCES := dual_int4_mac.v toy_attention_core.v project.v

ifneq ($(GATES),yes)
SIM_BUILD := $(BENCHMARK_DIR)/sim_build/rtl
BENCHMARK_MODE := rtl
BENCHMARK_GATE_NETLIST :=
BENCHMARK_PDK_ROOT :=
VERILOG_SOURCES += $(addprefix $(SRC_DIR)/,$(PROJECT_SOURCES))
else
SIM_BUILD := $(BENCHMARK_DIR)/sim_build/gate
BENCHMARK_MODE := gate
NETLIST ?= $(ROOT)/test/gate_level_netlist.v
ifndef PDK_ROOT
$(error PDK_ROOT must point to the Sky130 PDK root when GATES=yes)
endif
COMPILE_ARGS += -DGL_TEST -DFUNCTIONAL -DUSE_POWER_PINS -DSIM -DUNIT_DELAY=\#1
VERILOG_SOURCES += $(PDK_ROOT)/sky130A/libs.ref/sky130_fd_sc_hd/verilog/primitives.v
VERILOG_SOURCES += $(PDK_ROOT)/sky130A/libs.ref/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v
VERILOG_SOURCES += $(NETLIST)
BENCHMARK_GATE_NETLIST := $(abspath $(NETLIST))
BENCHMARK_PDK_ROOT := $(abspath $(PDK_ROOT))
endif

ifeq ($(BENCHMARK_KIND),active)
BENCHMARK_BASENAME := $(BENCHMARK_MODE)_warm_baseline
else ifeq ($(BENCHMARK_KIND),idle)
BENCHMARK_BASENAME := $(BENCHMARK_MODE)_idle_warm_window
else
$(error BENCHMARK_KIND must be active or idle)
endif

WAVEFORM ?= $(BENCHMARK_DIR)/results/$(BENCHMARK_BASENAME).vcd
BENCHMARK_OUTPUT ?= $(BENCHMARK_DIR)/results/$(BENCHMARK_BASENAME).json

VERILOG_SOURCES += $(BENCHMARK_DIR)/tb.v
COMPILE_ARGS += -I$(SRC_DIR)
COCOTB_PLUSARGS += +WAVEFORM=$(WAVEFORM)
TOPLEVEL := tb
COCOTB_TEST_MODULES := test_warm_benchmark

export BENCHMARK_MODE
export BENCHMARK_OUTPUT
export BENCHMARK_KIND
export BENCHMARK_GATE_NETLIST
export BENCHMARK_PDK_ROOT
export BENCHMARK_SIMULATOR := $(SIM)

.PHONY: benchmark verify-vcd
.DEFAULT_GOAL := benchmark

benchmark:
	$(MAKE) sim
	$(PYTHON) $(BENCHMARK_DIR)/verify_vcd_window.py $(BENCHMARK_OUTPUT) $(WAVEFORM)

verify-vcd:
	$(PYTHON) $(BENCHMARK_DIR)/verify_vcd_window.py $(BENCHMARK_OUTPUT) $(WAVEFORM)

include $(shell cocotb-config --makefiles)/Makefile.sim
