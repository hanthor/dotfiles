#!/bin/sh
# goose wrapper → deepseek-chat.py
# Translates old hive goose CLI calls to the DeepSeek Python chat loop.
exec python3 /usr/local/bin/deepseek-chat.py "$@"
