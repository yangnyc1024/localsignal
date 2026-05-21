FROM node:22-slim

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

RUN npm run build

RUN mkdir -p .next/standalone/.next \
  && cp -R .next/static .next/standalone/.next/static \
  && if [ -d public ]; then cp -R public .next/standalone/public; fi

ENV HOSTNAME=0.0.0.0
ENV PORT=3000

CMD ["node", ".next/standalone/server.js"]
