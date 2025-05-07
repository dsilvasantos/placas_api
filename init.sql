CREATE TABLE IF NOT EXISTS placas_autorizadas (
    id SERIAL PRIMARY KEY,
    placa VARCHAR(10) UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS capturas (
    id SERIAL PRIMARY KEY,
    placa VARCHAR(10) NOT NULL,
    status VARCHAR(10) NOT NULL,
    horario TIMESTAMP NOT NULL
);

grant all PRIVILEGES on placas_autorizadas to placa;
grant all PRIVILEGES on capturas to placa;
grant all PRIVILEGES on capturas_id_seq to placa;