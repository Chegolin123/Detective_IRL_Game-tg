"""Подключение к VPS для служебных скриптов.

Пароли и токены в коде не хранятся: всё берётся из переменных окружения.
По умолчанию — вход по SSH-ключу через tailnet-адрес (парольный вход на VPS
отключён, поэтому пароль тут не нужен).

Переменные окружения:
  SSH_HOST     — адрес VPS (по умолчанию tailnet 100.84.218.66)
  SSH_USER     — пользователь (по умолчанию root)
  SSH_KEY      — путь к приватному ключу (по умолчанию ~/.ssh/id_rsa)
  SSH_PASSWORD — только если ключа нет; лучше не использовать
"""
import os
import sys

import paramiko

SSH_HOST = os.getenv("SSH_HOST", "100.84.218.66")
SSH_USER = os.getenv("SSH_USER", "root")
SSH_KEY = os.getenv("SSH_KEY", os.path.expanduser("~/.ssh/id_rsa"))
SSH_PASSWORD = os.getenv("SSH_PASSWORD", "")

BOT_DIR = os.getenv("BOT_DIR", "/root/dark_moon_bot")


def connect():
    """Возвращает подключённый SSHClient или поднимает SystemExit с понятной причиной."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = {"hostname": SSH_HOST, "port": 22, "username": SSH_USER, "timeout": 20}
    if os.path.exists(SSH_KEY):
        kwargs["key_filename"] = SSH_KEY
    elif SSH_PASSWORD:
        kwargs["password"] = SSH_PASSWORD
    else:
        sys.exit(
            "Не найден SSH-ключ %s и не задан SSH_PASSWORD.\n"
            "Укажи ключ: set SSH_KEY=<путь> или скопируй id_rsa из ~/.ssh" % SSH_KEY
        )
    client.connect(**kwargs)
    return client


def run(ssh, cmd, timeout=30):
    """Выполняет команду и возвращает (stdout, stderr, код возврата)."""
    _stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    code = stdout.channel.recv_exit_status()
    return stdout.read().decode("utf-8"), stderr.read().decode("utf-8"), code
