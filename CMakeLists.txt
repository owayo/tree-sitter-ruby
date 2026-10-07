cmake_minimum_required(VERSION 3.13)

# リリース時に Cargo.toml だけを更新しても C 配布物のバージョンを同期する。
file(STRINGS "${CMAKE_CURRENT_SOURCE_DIR}/Cargo.toml" PACKAGE_VERSION_LINE
     REGEX "^version = ")
string(REGEX REPLACE "version = \"([^\"]+)\"" "\\1"
       TREE_SITTER_RUBY_VERSION "${PACKAGE_VERSION_LINE}")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS Cargo.toml)

project(tree-sitter-ruby
        VERSION "${TREE_SITTER_RUBY_VERSION}"
        DESCRIPTION "Ruby grammar for tree-sitter"
        HOMEPAGE_URL "https://github.com/owayo/tree-sitter-ruby"
        LANGUAGES C)

option(BUILD_SHARED_LIBS "Build using shared libraries" ON)
option(TREE_SITTER_REUSE_ALLOCATOR "Reuse the library allocator" OFF)

set(TREE_SITTER_ABI_VERSION 15 CACHE STRING "Tree-sitter ABI version")
if(NOT ${TREE_SITTER_ABI_VERSION} MATCHES "^[0-9]+$")
    unset(TREE_SITTER_ABI_VERSION CACHE)
    message(FATAL_ERROR "TREE_SITTER_ABI_VERSION must be an integer")
endif()

find_program(TREE_SITTER_CLI tree-sitter DOC "Tree-sitter CLI")

# 通常のビルドは生成済みソースを使い、利用者の環境で勝手に再生成しない。
if(TREE_SITTER_CLI)
  add_custom_target(ts-generate
                    COMMAND "${TREE_SITTER_CLI}" generate
                            --abi=${TREE_SITTER_ABI_VERSION}
                    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
                    COMMENT "Ruby 文法からパーサーを再生成")
endif()

add_library(tree-sitter-ruby src/parser.c)
if(EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/src/scanner.c)
  target_sources(tree-sitter-ruby PRIVATE src/scanner.c)
endif()
target_include_directories(tree-sitter-ruby PRIVATE src)
target_compile_options(tree-sitter-ruby PRIVATE
                       $<$<C_COMPILER_ID:MSVC>:/utf-8>)

target_compile_definitions(tree-sitter-ruby PRIVATE
                           $<$<BOOL:${TREE_SITTER_REUSE_ALLOCATOR}>:TREE_SITTER_REUSE_ALLOCATOR>
                           $<$<CONFIG:Debug>:TREE_SITTER_DEBUG>)

set_target_properties(tree-sitter-ruby
                      PROPERTIES
                      C_STANDARD 11
                      POSITION_INDEPENDENT_CODE ON
                      SOVERSION "${TREE_SITTER_ABI_VERSION}.${PROJECT_VERSION_MAJOR}"
                      DEFINE_SYMBOL "")

include(GNUInstallDirs)

configure_file(bindings/c/tree-sitter-ruby.pc.in
               "${CMAKE_CURRENT_BINARY_DIR}/tree-sitter-ruby.pc" @ONLY)

install(FILES bindings/c/tree-sitter-ruby.h
        DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}/tree_sitter")
install(FILES "${CMAKE_CURRENT_BINARY_DIR}/tree-sitter-ruby.pc"
        DESTINATION "${CMAKE_INSTALL_DATAROOTDIR}/pkgconfig")
install(TARGETS tree-sitter-ruby
        LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}")

find_package(Python3 3.7 COMPONENTS Interpreter QUIET)
if(BUILD_SHARED_LIBS AND Python3_Interpreter_FOUND)
  add_custom_target(ts-test
                    COMMAND "${CMAKE_COMMAND}" -E env
                            "TREE_SITTER_LIB_PATH=$<TARGET_FILE:tree-sitter-ruby>"
                            "${Python3_EXECUTABLE}" scripts/corpus_test.py
                    DEPENDS tree-sitter-ruby
                    WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
                    COMMENT "低メモリのコーパステストを実行")
endif()
