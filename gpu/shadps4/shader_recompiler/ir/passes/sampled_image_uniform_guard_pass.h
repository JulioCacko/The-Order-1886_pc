// SPDX-FileCopyrightText: Copyright 2026 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

#include <span>
#include "shader_recompiler/ir/basic_block.h"
#include "shader_recompiler/ir/passes/resource_pass.h"

namespace Shader::Optimization {
// Kept independent of Info/Vulkan so the actual CFG and all-use analysis is CPU-testable.
void AnalyzeSampledImageUniformGuards(std::span<IR::Block* const> blocks,
                                     ResourceDiscoveryList& resources);
}
