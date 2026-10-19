'use strict';

// Lance l'application dans Chromium contre le serveur local du projet (port
// libre), avec un contexte neuf par test : aucune donnee persistante, aucun
// acces au dossier %AppData% de l'application installee.
const path = require('path');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const { getRacineApp } = require('./racine');

const VIEWPORT = { width: 1440, height: 900 };

async function demarrerApp() {
  const { startServer } = require(path.join(getRacineApp(), 'serve-app.js'));
  const { server, port } = await startServer(0);
  assert.ok(Number.isInteger(port) && port > 0, `port libre attendu, recu ${port}`);
  const browser = await chromium.launch();
  return {
    port,
    url: `http://127.0.0.1:${port}/`,
    browser,
    async fermer() {
      await browser.close().catch(() => {});
      await new Promise(resolve => server.close(() => resolve()));
    },
  };
}

// Neutralise toute impression : window.print est remplace dans la page et dans
// chaque fenetre ouverte (avant meme que la fenetre n'ecrive son document).
function neutraliserImpression() {
  window.__printAppels = 0;
  window.print = () => { window.__printAppels += 1; };
  const ouvrir = window.open;
  window.open = function (...args) {
    const fenetre = ouvrir.apply(this, args);
    try {
      if (fenetre) {
        fenetre.__printAppels = 0;
        fenetre.print = () => { fenetre.__printAppels += 1; };
      }
    } catch (err) { /* fenetre d'une autre origine : ignoree */ }
    return fenetre;
  };
}

async function ouvrirPage(app) {
  const context = await app.browser.newContext({ viewport: VIEWPORT, serviceWorkers: 'block' });
  await context.addInitScript(neutraliserImpression);
  const page = await context.newPage();
  const erreurs = [];
  page.on('pageerror', err => erreurs.push(err));
  await page.goto(app.url, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => window.TIL && typeof chargerDepuisJSON === 'function', null, { timeout: 15000 });
  return { context, page, erreurs };
}

// Charge un Tillys (objet serialisable) comme le ferait l'import d'un projet.
async function chargerTillys(page, tillys) {
  const donnees = JSON.parse(JSON.stringify(tillys));
  const ok = await page.evaluate(t => {
    const resultat = chargerDepuisJSON({ version: '2.0', projet: { nom: 'TEST' }, options: APP.options, tillys: [t] });
    APP.tillysActif = 0;
    return resultat;
  }, donnees);
  assert.equal(ok, true, 'chargerDepuisJSON doit accepter la fixture');

  // Precondition : le chargement ne doit pas deplacer les modules de la fixture.
  const modules = await page.evaluate(() => (APP.tillys[0].synopticModules || []).map(m => ({
    id: m.id, address: m.address, doorNums: [...(m.doorNums || [])],
  })));
  (donnees.synopticModules || []).forEach(attendu => {
    const charge = modules.find(m => m.id === attendu.id);
    assert.ok(charge, `module ${attendu.id} absent apres chargement`);
    assert.equal(charge.address, attendu.address, `adresse du module ${attendu.id} modifiee au chargement`);
    assert.deepEqual(charge.doorNums, attendu.doorNums, `portes du module ${attendu.id} modifiees au chargement`);
  });
}

// Ouvre la page, charge la fixture et renvoie de quoi fermer le contexte.
async function preparerPage(app, tillys) {
  const session = await ouvrirPage(app);
  if (tillys) await chargerTillys(session.page, tillys);
  return session;
}

// Declenche une action qui ouvre une fenetre et renvoie cette fenetre chargee.
async function capturerPopup(context, page, action) {
  const [popup] = await Promise.all([
    context.waitForEvent('page', { timeout: 10000 }),
    page.evaluate(action),
  ]);
  await popup.waitForLoadState('load');
  return popup;
}

// Attend le chargement reel d'une image et renvoie sa largeur naturelle.
async function largeurImage(popup, selecteur) {
  const presente = await popup.locator(selecteur).count();
  assert.ok(presente > 0, `image ${selecteur} absente du document`);
  await popup.waitForFunction(sel => {
    const img = document.querySelector(sel);
    return img && img.complete;
  }, selecteur, { timeout: 10000 });
  return popup.evaluate(sel => document.querySelector(sel).naturalWidth, selecteur);
}

module.exports = {
  VIEWPORT,
  demarrerApp,
  ouvrirPage,
  chargerTillys,
  preparerPage,
  capturerPopup,
  largeurImage,
};
