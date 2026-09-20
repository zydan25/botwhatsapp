module.exports = {
  apps: [
    {
      name: 'waseliyat',
      cwd: '/home/root/projects/waseliyat/waseliyat_whatsapp',
      script: '/home/root/projects/waseliyat/waseliyat_whatsapp/run.py',
      interpreter: '/home/root/projects/waseliyat/.venv/bin/python',
      autorestart: true,
      watch: false,
      max_memory_restart: '512M',
      time: true,
      env: {
        PYTHONUNBUFFERED: '1',
        FLASK_ENV: 'production',
      },
    },
  ],
};
