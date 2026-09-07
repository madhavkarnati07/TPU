.PHONY: setup verify test-python test-rtl test-pe test-attention check-python check-verilog clean

PYTHON ?= .venv/bin/python
SYSTEM_PYTHON ?= python3
IVERILOG ?= iverilog
VVP ?= vvp
MAC_LANES ?= 2
BUILD_DIR := .build
PE_TB := $(BUILD_DIR)/pe_tb.vvp
ATTENTION_TB := $(BUILD_DIR)/attention_mac$(MAC_LANES)_tb.vvp
ATTENTION_VECTORS := $(BUILD_DIR)/attention_vectors.vh

setup:
	$(SYSTEM_PYTHON) -m venv .venv
	$(PYTHON) -m pip install --requirement requirements-dev.txt

verify: test-python test-rtl

check-python:
	@test -x "$(PYTHON)" || (echo "Missing $(PYTHON). Run 'make setup' first." && exit 1)

check-verilog:
	@command -v $(IVERILOG) >/dev/null || (echo "Missing Icarus Verilog. On macOS run 'brew install icarus-verilog'." && exit 1)
	@command -v $(VVP) >/dev/null || (echo "Missing vvp. On macOS run 'brew install icarus-verilog'." && exit 1)

test-python: check-python
	$(PYTHON) -m pytest --import-mode=importlib -q

test-rtl: test-pe test-attention

test-pe: check-verilog $(PE_TB)
	mkdir -p $(BUILD_DIR)/build
	cd $(BUILD_DIR) && $(VVP) $(notdir $(PE_TB))

$(PE_TB): rtl/pe.v sim/tb_pe.v
	mkdir -p $(BUILD_DIR)
	$(IVERILOG) -g2012 -Wall -o $(PE_TB) rtl/pe.v sim/tb_pe.v

test-attention: check-python check-verilog $(ATTENTION_TB)
	mkdir -p $(BUILD_DIR)/build
	cd $(BUILD_DIR) && $(VVP) $(notdir $(ATTENTION_TB))

$(ATTENTION_VECTORS): toy_attention.py sim/generate_attention_vectors.py
	mkdir -p $(BUILD_DIR)
	$(PYTHON) sim/generate_attention_vectors.py $(ATTENTION_VECTORS)

$(ATTENTION_TB): $(ATTENTION_VECTORS) ../src/dual_int4_mac.v ../src/toy_attention_core.v ../src/project.v sim/tb_toy_attention.v
	mkdir -p $(BUILD_DIR)
	$(IVERILOG) -g2012 -Wall -I $(BUILD_DIR) -s tb_toy_attention -o $(ATTENTION_TB) \
		-Ptb_toy_attention.MAC_LANES=$(MAC_LANES) \
		../src/dual_int4_mac.v ../src/toy_attention_core.v \
		../src/project.v sim/tb_toy_attention.v

clean:
	rm -rf $(BUILD_DIR)
