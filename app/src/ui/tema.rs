//! Cores e tipografia do painel (as mesmas do painel.html, escuro).

use rune::Color;
use rune::tok::TextStyle;
use rune_kit::{Kit, PaletteSeed};

fn h(s: &str) -> Color { rune::color::hex(s).unwrap_or(Color::BLACK) }

#[derive(Clone, Copy)]
pub struct Tema {
    pub bg: Color,
    pub card: Color,
    pub card2: Color,
    pub linha: Color,
    pub linha_forte: Color,
    pub txt: Color,
    pub dim: Color,
    pub acento: Color,
    pub alerta: Color,
    pub erro: Color,
    pub rep: Color,
}

pub fn tema() -> Tema {
    Tema {
        bg: h("#0e1013"),
        card: h("#171a1f"),
        card2: h("#1e222a"),
        linha: h("#2a2f39"),
        linha_forte: h("#3d4653"),
        txt: h("#e8eaee"),
        dim: h("#98a0ae"),
        acento: h("#4ad3a0"),
        alerta: h("#e2b04a"),
        erro: h("#e2695f"),
        rep: h("#7aa2f7"),
    }
}

pub fn kit() -> Kit {
    let t = tema();
    Kit::from_palette(PaletteSeed { bg: t.bg, fg: t.txt, accent: t.acento })
}

/// Cor de cada pilar (pastilhas e etiqueta do card).
pub fn cor_pilar(i: usize) -> Color {
    const C: [&str; 7] = ["#4ad3a0", "#7aa2f7", "#e2b04a", "#c792ea", "#f78c6c", "#89ddff", "#98a0ae"];
    h(C[i % C.len()])
}

pub const TITULO: TextStyle = TextStyle::new(15.0, 600.0);
pub const NORMAL: TextStyle = TextStyle::new(13.0, 400.0);
pub const NORMAL_M: TextStyle = TextStyle::new(13.0, 500.0);
pub const PEQ: TextStyle = TextStyle::new(11.5, 400.0);
pub const PEQ_M: TextStyle = TextStyle::new(11.5, 600.0);
pub const MINI: TextStyle = TextStyle::new(10.5, 600.0);
pub const NOTA: TextStyle = TextStyle::new(20.0, 600.0);
pub const MONO: TextStyle = TextStyle::new(11.5, 400.0).mono();

/// Texto sobre o verde de destaque.
pub const TINTA_ACENTO: Color = Color { r: 0.0024, g: 0.0144, b: 0.0110, a: 1.0 };
