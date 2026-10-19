'use strict';

// Charge app/generator.js dans un bac a sable : le fichier est ecrit pour le
// navigateur et publie son API sur window.TIL.
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { getRacineApp } = require('./racine');

function chargerGenerator() {
  const fichier = path.join(getRacineApp(), 'app', 'generator.js');
  const source = fs.readFileSync(fichier, 'utf8');
  const sandbox = { window: {}, console: { log() {}, warn() {}, info() {} } };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, { filename: fichier });
  if (!sandbox.window.TIL) throw new Error(`window.TIL absent apres chargement de ${fichier}`);
  return sandbox.window.TIL;
}

module.exports = { chargerGenerator };
