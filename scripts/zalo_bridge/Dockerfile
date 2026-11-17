FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install --production

COPY index.mjs ./

EXPOSE 5055

CMD ["node", "index.mjs"]
