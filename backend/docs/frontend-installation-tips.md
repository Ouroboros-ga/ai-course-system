```bash
sudo apt update
sudo apt install -y curl
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
node -v
npm -v
```
大致输出：
```text
v20.x.x
10.x.x
```

```bash
cd /home/will_m/projects/ai-course-system/frontend

rm -rf node_modules package-lock.json
npm install
npm run dev
```
