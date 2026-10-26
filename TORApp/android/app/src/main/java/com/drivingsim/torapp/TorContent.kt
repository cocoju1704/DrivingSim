package com.drivingsim.torapp

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.text.Layout
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.StaticLayout
import android.text.TextPaint
import android.text.style.ForegroundColorSpan
import com.meta.wearable.dat.display.views.ContentScope
import com.meta.wearable.dat.display.views.Direction
import com.meta.wearable.dat.display.views.ImageSize
import com.meta.wearable.dat.display.views.TextColor
import com.meta.wearable.dat.display.views.TextStyle

// The display SDK has no text colors or positions (TextColor: PRIMARY / SECONDARY only), so each
// view is drawn here as one 600x600 image and sent whole.
private const val WIDTH = 600 // display width and height in pixels
private const val PADDING = 32f
private const val IMAGE_SCALE = 0.5f // images are drawn at half the display resolution
private val ORANGE = Color.rgb(255, 140, 0) // PRE-ALERT, as on the simulator screen
private val RED = Color.rgb(255, 0, 0) // TOR: the brightest red the display can show
private val DARK_RED = Color.rgb(150, 0, 0) // blink test: the dark half of the flash
private val MODE_AUTO = Color.rgb(0, 190, 70) // mode badge background: saturated, bright on the additive
private val MODE_MANUAL = Color.rgb(30, 110, 255) // display, dark enough for the white text on it
private const val MODE_ON_RIGHT = true // mode badge at the bottom right; false: bottom left
private val LABEL = Color.rgb(0, 255, 255) // intervention text: the label before the ':', bright cyan stands out on the additive display
private const val TEXT_HEIGHT = 480 // intervention text: from the top, above the mode text

/**
 * The overlay of takeover_experiment.py (TakeoverExperiment.render) on the glasses, without
 * backgrounds so the road stays visible. The display is 600x600, additive (black is see-through)
 * and in the right lens only; its top edge is at the center of the field of view.
 *   AUTO / MANUAL   small oval badge (white text on green / blue) at the bottom right
 *   PRE_ALERT       first seconds (TorViewModel): "PRE-ALERT" and the message in orange in the
 *                   center, no time left; then the intervention text at the top
 *   TOR             "TAKE OVER" in red at the top, countdown digits and bar at the bottom
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
    image(bitmap = frame(view), sizePreset = ImageSize.FILL)
  }
}

private fun frame(view: GlassesView): Bitmap {
  val showText = view.mode == TorMode.PRE_ALERT && view.seconds == null && view.text.isNotEmpty()
  // full resolution only with the Korean text, which is unreadable at IMAGE_SCALE
  val (bitmap, canvas) = blank(WIDTH, scale = if (showText) 1f else IMAGE_SCALE)
  if (view.mode == TorMode.TOR) {
    drawTor(canvas, view)
    return bitmap
  }
  if (showText) drawText(canvas, view.text)
  if (view.mode == TorMode.PRE_ALERT && view.seconds != null) drawPreAlert(canvas, view.message)
  drawMode(canvas, view)
  return bitmap
}

/** "TAKE OVER" in red at the top, the countdown digits and bar in red at the bottom. */
private fun drawTor(canvas: Canvas, view: GlassesView) {
  val color = if (view.dim) DARK_RED else RED
  val center = WIDTH / 2f
  val maxWidth = WIDTH - 2 * PADDING
  val words = textPaint(84f, bold = true).apply { this.color = color; textAlign = Paint.Align.CENTER }
  canvas.drawText("TAKE OVER", center, 100f, fit(words, "TAKE OVER", maxWidth))
  val seconds = "${view.seconds ?: 0}"
  val digits = textPaint(80f, bold = true).apply { this.color = color; textAlign = Paint.Align.CENTER }
  canvas.drawText(seconds, center, 520f, fit(digits, seconds, maxWidth))
  val fraction = view.seconds?.let { s -> view.total?.let { (s / it).toFloat() } }
  if (fraction != null) {
    val barWidth = (WIDTH - 2 * PADDING) * fraction.coerceIn(0f, 1f)
    canvas.drawRect(PADDING, 556f, PADDING + barWidth, 576f, fillPaint(color))
  }
}

/** "PRE-ALERT" and the message in orange in the center, like TAKE OVER. No time left. */
private fun drawPreAlert(canvas: Canvas, message: String) {
  val center = WIDTH / 2f
  val maxWidth = WIDTH - 2 * PADDING
  val title = textPaint(84f, bold = true).apply { color = ORANGE; textAlign = Paint.Align.CENTER }
  canvas.drawText("PRE-ALERT", center, 300f, fit(title, "PRE-ALERT", maxWidth))
  if (message.isNotEmpty()) {
    val subtitle = message.replaceFirstChar { it.uppercase() }
    val small = textPaint(40f, bold = true).apply { color = ORANGE; textAlign = Paint.Align.CENTER }
    canvas.drawText(subtitle, center, 360f, fit(small, subtitle, maxWidth))
  }
}

/**
 * Small oval badge at the bottom right (MODE_ON_RIGHT, else left): AUTO on green while autonomous
 * (also during the alerts), MANUAL on blue, white text. Short on purpose; the simulator's longer
 * label (view.label) is not used here.
 */
private fun drawMode(canvas: Canvas, view: GlassesView) {
  val text = if (view.mode == TorMode.MANUAL) "MANUAL" else "AUTO"
  val paint = textPaint(45f, bold = true)
  val height = 78f
  val width = paint.measureText(text) + height // half the height of padding on each side
  val left = if (MODE_ON_RIGHT) WIDTH - PADDING - width else PADDING
  val top = WIDTH - PADDING - height
  canvas.drawRoundRect(
      RectF(left, top, left + width, top + height), height / 2, height / 2,
      fillPaint(if (view.mode == TorMode.MANUAL) MODE_MANUAL else MODE_AUTO))
  val metrics = paint.fontMetrics
  canvas.drawText(text, left + height / 2, top + height / 2 - (metrics.ascent + metrics.descent) / 2, paint)
}

/**
 * Intervention lines in bold white from the top, wrapped to the display width, a gap between
 * lines. The part of a line up to its first ':' (the label, e.g. "완료된 작업:") is in bright cyan,
 * on a line of its own, the rest below it. The font starts large and shrinks until all of it fits
 * in TEXT_HEIGHT.
 */
private fun drawText(canvas: Canvas, lines: List<String>) {
  val text = SpannableStringBuilder()
  for ((i, line) in lines.withIndex()) {
    if (i > 0) text.append('\n')
    val colon = line.indexOf(':')
    if (colon > 0) {
      val start = text.length
      text.append(line, 0, colon + 1)
      text.setSpan(ForegroundColorSpan(LABEL), start, text.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
      text.append('\n').append(line.substring(colon + 1).trim())
    } else {
      text.append(line)
    }
  }
  val width = (WIDTH - 2 * PADDING).toInt()
  var size = 64f
  var layout: StaticLayout
  while (true) {
    val paint =
        TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
          color = Color.WHITE
          textSize = size
          typeface = Typeface.DEFAULT_BOLD
        }
    layout =
        StaticLayout.Builder.obtain(text, 0, text.length, paint, width)
            .setAlignment(Layout.Alignment.ALIGN_NORMAL)
            .setLineSpacing(size * 0.25f, 1f)
            .build()
    if (layout.height <= TEXT_HEIGHT || size <= 28f) break
    size -= 2f
  }
  canvas.save()
  canvas.translate(PADDING, 0f)
  layout.draw(canvas)
  canvas.restore()
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
