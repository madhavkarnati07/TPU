.PHONY: test-pe clean

IVERILOG ?= iverilog
VVP ?= vvp
BUILD_DIR := build
PE_TB := $(BUILD_DIR)/pe_tb.vvp

test-pe: $(PE_TB)
	$(VVP) $(PE_TB)

$(PE_TB): rtl/pe.v sim/tb_pe.v
	mkdir -p $(BUILD_DIR)
	$(IVERILOG) -g2012 -Wall -o $(PE_TB) rtl/pe.v sim/tb_pe.v

clean:
	rm -rf $(BUILD_DIR)
