package com.drivingsim.torapp

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import com.meta.wearable.dat.display.views.ContentScope
import com.meta.wearable.dat.display.views.Direction
import com.meta.wearable.dat.display.views.ImageSize
import com.meta.wearable.dat.display.views.TextColor
import com.meta.wearable.dat.display.views.TextStyle

// The display SDK has no text or background colors (TextColor: PRIMARY / SECONDARY only), so the
// colored banners are drawn here and sent as images.
private const val WIDTH = 600 // display width in pixels
private const val PADDING = 32f
private const val IMAGE_SCALE = 0.5f // images are drawn at half the display resolution
private val GREEN = Color.rgb(40, 160, 70) // the colors of the banners on the simulator screen
private val ORANGE = Color.rgb(255, 140, 0)
private val RED = Color.rgb(255, 0, 0) // TOR: the brightest red the display can show
private val DARK_RED = Color.rgb(150, 0, 0) // blink test: the dark half of the flash
private val BLUE = Color.rgb(40, 110, 200)

/**
 * The overlay of takeover_experiment.py (TakeoverExperiment.render) on the glasses: the mode box
 * at the top and, during the takeover sequence, the PRE-ALERT / TOR banner with its countdown bar.
 * The display is 600x600, additive (black is see-through) and in the right lens only.
 */
fun ContentScope.torContent(view: GlassesView) {
  when (view.test) {
    DisplayTest.AREA -> {
      flexBox { image(bitmap = areaTest(), sizePreset = ImageSize.FILL) }
      return
    }
    DisplayTest.TEXT -> {
      textTest()
      return
    }
    null -> Unit
  }
  flexBox(direction = Direction.COLUMN, gap = 12) {
    if (view.mode == TorMode.OFF) {
      text("TORApp", style = TextStyle.BODY)
      text("Waiting for the simulator", style = TextStyle.META, color = TextColor.SECONDARY)
      return@flexBox
    }
    if (view.mode == TorMode.TOR) { // the whole display, nothing else
      image(bitmap = torFullScreen(view), sizePreset = ImageSize.FILL)
      return@flexBox
    }
    image(bitmap = modeBox(view), sizePreset = ImageSize.FILL)
    val fraction = view.seconds?.let { seconds -> view.total?.let { (seconds / it).toFloat() } }
    when (view.mode) {
      TorMode.PRE_ALERT ->
          image(
              bitmap =
                  banner(
                      ORANGE,
                      "PRE-ALERT",
                      listOf(view.message, "takeover request in ${view.seconds ?: 0} s")
                          .filter { it.isNotEmpty() }
                          .joinToString(" - ")
                          .replaceFirstChar { it.uppercase() },
                      fraction,
                  ),
              sizePreset = ImageSize.FILL,
          )
      else -> Unit
    }
  }
}

/**
 * TOR as large and bright as the display allows: all 600x600 pixels red at full intensity, the
 * largest white text that fits, the countdown in big digits and the countdown bar at the bottom.
 */
private fun torFullScreen(view: GlassesView): Bitmap {
  val (bitmap, canvas) = blank(WIDTH)
  // rounded corners: a few transparent pixels make the SDK send PNG, not JPEG (half the size)
  canvas.drawRoundRect(
      RectF(0f, 0f, WIDTH.toFloat(), WIDTH.toFloat()), 24f, 24f, fillPaint(if (view.dim) DARK_RED else RED))
  val center = WIDTH / 2f
  val maxWidth = WIDTH - PADDING
  val words = textPaint(150f, bold = true).apply { textAlign = Paint.Align.CENTER }
  canvas.drawText("TAKE", center, 150f, fit(words, "OVER", maxWidth))
  canvas.drawText("OVER", center, 290f, words)
  val seconds = "${view.seconds ?: 0}"
  val digits = textPaint(170f, bold = true).apply { textAlign = Paint.Align.CENTER }
  canvas.drawText(seconds, center, 470f, fit(digits, seconds, maxWidth))
  val fraction = view.seconds?.let { s -> view.total?.let { (s / it).toFloat() } }
  if (fraction != null) {
    val barWidth = (WIDTH - 2 * PADDING) * fraction.coerceIn(0f, 1f)
    canvas.drawRect(PADDING, 530f, PADDING + barWidth, 560f, fillPaint(Color.WHITE))
  }
  return bitmap
}

/** The mode box: green while autonomous (also during the alerts), blue in manual driving. */
private fun modeBox(view: GlassesView): Bitmap {
  val text =
      view.label.ifEmpty {
        when (view.mode) {
          TorMode.AUTO -> "AUTONOMOUS - LOCKED"
          TorMode.MANUAL -> "MANUAL"
          else -> "AUTONOMOUS"
        }
      }
  return label(if (view.mode == TorMode.MANUAL) BLUE else GREEN, text)
}

/** Full-width banner like the screen's: title, subtitle and the countdown bar, centered, in white. */
private fun banner(color: Int, title: String, subtitle: String, fraction: Float?): Bitmap {
  val titlePaint = textPaint(60f, bold = true).apply { textAlign = Paint.Align.CENTER }
  val subtitlePaint = textPaint(36f, bold = false).apply { textAlign = Paint.Align.CENTER }
  val height = 220
  val (bitmap, canvas) = blank(height)
  val center = WIDTH / 2f
  canvas.drawRoundRect(RectF(0f, 0f, WIDTH.toFloat(), height.toFloat()), 36f, 36f, fillPaint(color))
  canvas.drawText(title, center, 88f, fit(titlePaint, title))
  canvas.drawText(subtitle, center, 146f, fit(subtitlePaint, subtitle))
  if (fraction != null) {
    val barWidth = (WIDTH - 2 * PADDING) * fraction.coerceIn(0f, 1f)
    canvas.drawRoundRect(
        RectF(PADDING, 176f, PADDING + barWidth, 188f), 6f, 6f, fillPaint(Color.WHITE))
  }
  return bitmap
}

/** Small centered pill with a bold white label. */
private fun label(color: Int, text: String): Bitmap {
  val paint = fit(textPaint(44f, bold = true), text, WIDTH - 4 * PADDING)
  val height = 96
  val (bitmap, canvas) = blank(height)
  val width = paint.measureText(text) + 2 * PADDING
  val left = (WIDTH - width) / 2f
  canvas.drawRoundRect(RectF(left, 8f, left + width, height - 8f), 40f, 40f, fillPaint(color))
  val metrics = paint.fontMetrics
  canvas.drawText(text, left + PADDING, height / 2f - (metrics.ascent + metrics.descent) / 2f, paint)
  return bitmap
}

/** 600x600: white border, 100 px grid with labels, center cross. Shows what part is visible. */
private fun areaTest(): Bitmap {
  val (bitmap, canvas) = blank(WIDTH, scale = 1f) // full resolution: it measures the display
  val grid = Paint().apply { color = Color.rgb(90, 90, 90); strokeWidth = 2f }
  val bright = Paint().apply { color = Color.WHITE; strokeWidth = 4f; style = Paint.Style.STROKE }
  val labels = textPaint(22f, bold = false).apply { color = Color.rgb(200, 200, 200) }
  for (x in 100 until WIDTH step 100) {
    canvas.drawLine(x.toFloat(), 0f, x.toFloat(), WIDTH.toFloat(), grid)
    canvas.drawLine(0f, x.toFloat(), WIDTH.toFloat(), x.toFloat(), grid)
    canvas.drawText("$x", x + 4f, 24f, labels)
    canvas.drawText("$x", 6f, x - 6f, labels)
  }
  canvas.drawRect(2f, 2f, WIDTH - 2f, WIDTH - 2f, bright)
  val c = WIDTH / 2f
  canvas.drawLine(c - 40f, c, c + 40f, c, bright)
  canvas.drawLine(c, c - 40f, c, c + 40f, bright)
  val corner = fillPaint(Color.rgb(255, 140, 0))
  for ((x, y) in listOf(0f to 0f, WIDTH - 40f to 0f, 0f to WIDTH - 40f, WIDTH - 40f to WIDTH - 40f)) {
    canvas.drawRect(x, y, x + 40f, y + 40f, corner)
  }
  val title = textPaint(40f, bold = true).apply { textAlign = Paint.Align.CENTER }
  canvas.drawText("600 x 600", c, c + 90f, title)
  return bitmap
}

/** Native text in the three styles, numbered, so the visible lines and the scrolling show. */
private fun ContentScope.textTest() {
  flexBox(direction = Direction.COLUMN, gap = 4) {
    text("HEADING 1 TAKE OVER NOW!", style = TextStyle.HEADING)
    text("HEADING 2 Manual driving in 5 s", style = TextStyle.HEADING)
    for (i in 1..12) {
      text("BODY $i  The quick brown fox jumps over the lazy dog", style = TextStyle.BODY)
    }
    for (i in 1..6) {
      text("META $i  The quick brown fox jumps over the lazy dog", style = TextStyle.META)
    }
    text("END", style = TextStyle.HEADING)
  }
}

/**
 * Transparent bitmap (see-through on the glasses, like black) and a canvas drawing in display
 * pixels (600 wide). The SDK sends each image whole over Bluetooth, PNG when it has transparent
 * pixels: drawn at IMAGE_SCALE of the display size and stretched back by ImageSize.FILL, a view
 * is about a quarter of the data, so the countdown keeps up with the PC.
 */
private fun blank(height: Int, scale: Float = IMAGE_SCALE): Pair<Bitmap, Canvas> {
  val bitmap =
      Bitmap.createBitmap((WIDTH * scale).toInt(), (height * scale).toInt(), Bitmap.Config.ARGB_8888)
  bitmap.eraseColor(Color.TRANSPARENT)
  return bitmap to Canvas(bitmap).apply { scale(scale, scale) }
}

private fun fillPaint(color: Int) =
    Paint(Paint.ANTI_ALIAS_FLAG).apply {
      this.color = color
      style = Paint.Style.FILL
    }

private fun textPaint(size: Float, bold: Boolean) =
    Paint(Paint.ANTI_ALIAS_FLAG).apply {
      color = Color.WHITE
      textSize = size
      typeface = if (bold) Typeface.DEFAULT_BOLD else Typeface.DEFAULT
    }

/** Shrinks the text until it fits in maxWidth. */
private fun fit(paint: Paint, text: String, maxWidth: Float = WIDTH - 2 * PADDING): Paint {
  while (paint.measureText(text) > maxWidth && paint.textSize > 20f) {
    paint.textSize -= 2f
  }
  return paint
}
