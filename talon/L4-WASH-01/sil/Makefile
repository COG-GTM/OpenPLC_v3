# SIL build for L4_WASH_01
#
#   make            -> build/libl4wash_sil.so
#   make test       -> build + pytest
#   make clean
#
# Uses the same toolchain the runtime uses: iec2c (MatIEC) from webserver/,
# glue_generator from webserver/core/, g++ with the runtime's lib/ headers.
# Run ./install.sh <platform> at the repo root once so those binaries exist.

REPO_ROOT   := $(abspath $(CURDIR)/../../..)
WEBSERVER   := $(REPO_ROOT)/webserver
IEC2C       := $(WEBSERVER)/iec2c
GLUE_GEN    := $(WEBSERVER)/core/glue_generator
IEC_LIB     := $(WEBSERVER)/core/lib
MATIEC_LIB  := $(REPO_ROOT)/utils/matiec_src/lib

ST_FILE     := $(abspath $(CURDIR)/../L4_WASH_01.st)
BUILD       := $(CURDIR)/build
TARGET      := $(BUILD)/libl4wash_sil.so

CXX         ?= g++
CXXFLAGS    := -std=gnu++11 -O1 -fPIC -w -fpermissive -I $(IEC_LIB) -I $(BUILD)

# POUS.c is #included by Res0.c, exactly as compile_program.sh does it.
OBJS        := $(BUILD)/Res0.o $(BUILD)/Config0.o $(BUILD)/glueVars.o $(BUILD)/sil_shim.o

.PHONY: all test clean check-tools

all: $(TARGET)

check-tools:
	@test -x $(IEC2C) || { echo "iec2c not found at $(IEC2C) - run ./install.sh at repo root first"; exit 1; }
	@test -x $(GLUE_GEN) || { echo "glue_generator not found at $(GLUE_GEN) - run ./install.sh at repo root first"; exit 1; }

$(BUILD)/POUS.c $(BUILD)/Res0.c $(BUILD)/Config0.c $(BUILD)/LOCATED_VARIABLES.h $(BUILD)/VARIABLES.csv: $(ST_FILE) | check-tools
	@mkdir -p $(BUILD)
	cd $(BUILD) && $(IEC2C) -f -l -p -r -R -a -I $(MATIEC_LIB) $(ST_FILE)

$(BUILD)/glueVars.cpp: $(BUILD)/LOCATED_VARIABLES.h
	$(GLUE_GEN) $(BUILD)/LOCATED_VARIABLES.h $(BUILD)/glueVars.cpp

# MatIEC emits .c but the runtime compiles it with g++; keep that behaviour.
$(BUILD)/%.o: $(BUILD)/%.c
	$(CXX) $(CXXFLAGS) -x c++ -c $< -o $@

$(BUILD)/glueVars.o: $(BUILD)/glueVars.cpp
	$(CXX) $(CXXFLAGS) -c $< -o $@

$(BUILD)/sil_shim.o: $(CURDIR)/sil_shim.cpp $(BUILD)/LOCATED_VARIABLES.h
	$(CXX) $(CXXFLAGS) -c $< -o $@

$(TARGET): $(OBJS)
	$(CXX) -shared -o $@ $(OBJS) -lrt

test: $(TARGET)
	python3 -m pytest -q

clean:
	rm -rf $(BUILD) .pytest_cache __pycache__
