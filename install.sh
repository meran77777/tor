#!/bin/bash

# دانلود فایل torx.py
wget https://raw.githubusercontent.com/meran77777/tor/refs/heads/main/torx.py -O torx.py

# تغییر دسترسی به فایل torx.py
chmod 777 torx.py

# ایجاد دایرکتوری
mkdir -p /usr/share/torx

# کپی کردن فایل به دایرکتوری
cp torx.py /usr/share/torx/torx.py

# ایجاد اسکریپت برای اجرای torx.py
cmnd='#! /bin/sh \n exec python3 /usr/share/torx/torx.py "$@"'
echo -e $cmnd > /usr/bin/torx

# تغییر دسترسی به اسکریپت
chmod +x /usr/bin/torx
chmod +x /usr/share/torx/torx.py

# اجرای برنامه torx
torx

echo "Installation completed successfully."
